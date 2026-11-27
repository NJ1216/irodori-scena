from __future__ import annotations

from server.modules.script_line_deletion_routes import delete_lines  # noqa: F401

from server.app_deps import secrets, time, Path, Any, Callable, HTTPException
from server.registry import deps
from server.modules.line_synthesis_inputs import line_speech_timing, line_spoken_text
from server.modules.lora_reference import generation_lora
from server.modules.lora_mix import generation_mix
from server.modules.take_restoration import validate_take_execution, validate_take_runtime


@deps.app.delete("/api/scenes/{scene_id}/lines/{line_id}")
def delete_line(scene_id: str, line_id: str) -> dict[str, Any]:
    with deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        scene = next((item for item in project.get("scenes", []) if item.get("id") == scene_id), None)
        if scene is None:
            raise HTTPException(status_code=404, detail="Scene not found.")
        line = next((item for item in scene.get("lines", []) if item.get("id") == line_id), None)
        if line is None:
            raise HTTPException(status_code=404, detail="Dialogue line not found.")
        scene["lines"] = [item for item in scene.get("lines", []) if item.get("id") != line_id]
        deps.normalize_scene_cues(scene)
        deps.write_project(project)
    # Delete media after the project lock is released; the JSON no longer references it.
    _discard_take_directory(line_id)
    return project


def _discard_take_directory(line_id: str) -> None:
    try:
        deps.remove_line_takes(line_id)
    except OSError:
        pass


@deps.app.delete("/api/scenes/{scene_id}")
def delete_scene(scene_id: str) -> dict[str, Any]:
    with deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        scene = next((item for item in project.get("scenes", []) if item.get("id") == scene_id), None)
        if scene is None:
            raise HTTPException(status_code=404, detail="Scene not found.")
        project["scenes"] = [item for item in project.get("scenes", []) if item.get("id") != scene_id]
        deps.write_project(project)
    for line in scene.get("lines", []):
        _discard_take_directory(str(line.get("id", "")))
    return project


@deps.app.post("/api/scenes/{scene_id}/lines")
def insert_line(scene_id: str, request: deps.InsertLineRequest) -> dict[str, Any]:
    """Persist a blank line or atomically split an existing dialogue line."""
    with deps.PROJECT_ROOT_LOCK:
        return _insert_line_locked(scene_id, request)


def _insert_line_locked(scene_id: str, request: deps.InsertLineRequest) -> dict[str, Any]:
    project = deps.read_project()
    scene = next((item for item in project.get("scenes", []) if item.get("id") == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    if request.split_line_id:
        if request.split_offset is None:
            raise HTTPException(status_code=422, detail="Split position is required.")
        deps.split_dialogue_line(scene, request.split_line_id, request.split_offset, deps.new_id("line"))
        deps.write_project(project)
        return project
    lines = scene.get("lines", [])
    insert_index = len(lines)
    if request.before_line_id:
        insert_index = next((index for index, line in enumerate(lines) if line.get("id") == request.before_line_id), -1)
        if insert_index < 0:
            raise HTTPException(status_code=404, detail="Insertion position was not found.")
        target_cue = deps.cue_for_line(scene, request.before_line_id)
        if target_cue:
            insert_index = lines.index(target_cue[0])
    nearby_line = lines[insert_index] if insert_index < len(lines) else lines[-1] if lines else None
    character_id = str(nearby_line.get("characterId", "")) if nearby_line else str((project.get("characters") or [{}])[0].get("id", ""))
    line = {
        "id": deps.new_id("line"),
        "characterId": character_id,
        "text": "",
        "stageDirection": "",
        "takes": [],
        "selectedTakeId": None,
    }
    lines.insert(insert_index, line)
    deps.write_project(project)
    return project


@deps.app.post("/api/scenes/{scene_id}/lines/{line_id}/cue-members")
def add_cue_member(scene_id: str, line_id: str, request: deps.AddCueMemberRequest) -> dict[str, Any]:
    with deps.PROJECT_ROOT_LOCK:
        return _add_cue_member_locked(scene_id, line_id, request)


def _add_cue_member_locked(scene_id: str, line_id: str, request: deps.AddCueMemberRequest) -> dict[str, Any]:
    project = deps.read_project()
    scene = next((item for item in project.get("scenes", []) if item.get("id") == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    cue = deps.cue_for_line(scene, line_id)
    if not cue:
        raise HTTPException(status_code=404, detail="Dialogue line not found.")
    if not any(str(item.get("id", "")) == request.character_id for item in project.get("characters", [])):
        raise HTTPException(status_code=404, detail="Character not found.")
    if any(str(item.get("characterId", "")) == request.character_id for item in cue):
        raise HTTPException(status_code=409, detail="同じ同時発話内でキャストを重複させることはできません。")
    cue_id = deps.cue_key(cue[0]) or deps.new_id("cue")
    for item in cue:
        item["cueId"] = cue_id
        item["startOffsetSeconds"] = deps.normalize_start_offset(item.get("startOffsetSeconds"))
    member = {
        "id": deps.new_id("line"),
        "cueId": cue_id,
        "startOffsetSeconds": 0.0,
        "characterId": request.character_id,
        "text": "",
        "stageDirection": "",
        "takes": [],
        "selectedTakeId": None,
    }
    lines = scene.get("lines", [])
    lines.insert(lines.index(cue[-1]) + 1, member)
    deps.write_project(project)
    return project


@deps.app.post("/api/scenes/{scene_id}/lines/{line_id}/cue-mix")
def mix_cue(scene_id: str, line_id: str) -> dict[str, Any]:
    project = deps.read_project()
    scene = next((item for item in project.get("scenes", []) if item.get("id") == scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    return deps.render_cue_mix(scene, line_id)


@deps.app.post("/api/lines/{leading_line_id}/overlap-mix")
def mix_adjacent_units(leading_line_id: str) -> dict[str, Any]:
    return deps.request_overlap(leading_line_id)


@deps.app.post("/api/project/clear-takes")
def clear_all_takes() -> dict[str, Any]:
    """Delete every generated dialogue take while keeping the script intact."""
    deps.require_tts_available()
    staged: list[Path] = []
    with deps.PROJECT_ROOT_LOCK:
        saved = deps.clear_project_takes(deps.read_project(), deferred=staged)
    for path in staged:
        deps.discard_staged_takes(path)
    return saved


@deps.app.post("/api/lines/cleanup-takes")
def cleanup_selected_takes(request: dict[str, Any]) -> dict[str, Any]:
    deps.require_tts_available()
    line_ids = request.get("line_ids")
    if not isinstance(line_ids, list) or any(not isinstance(value, str) for value in line_ids):
        raise HTTPException(status_code=422, detail="Invalid line IDs.")
    with deps.PROJECT_ROOT_LOCK:
        return deps.cleanup_line_takes(deps.read_project(), line_ids, str(request.get("mode", "")))


def create_line_take(
    project: dict[str, Any],
    line: dict[str, Any],
    quality: str,
    *,
    take_id: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
    seed_override: int | None = None,
    restore_take: dict[str, Any] | None = None,
) -> dict[str, Any]:
    line_id = str(line.get("id", "")).strip()
    if not line_id:
        raise HTTPException(status_code=422, detail="Dialogue line has no ID.")
    character = deps.find_character(project, str(line.get("characterId", "")))
    reference = Path(str(character.get("referenceFile", ""))).resolve()
    if not reference.is_file():
        raise HTTPException(status_code=422, detail="This character has no saved reference WAV.")
    legacy_restore = restore_take is not None and restore_take.get("loraMix") is None
    lora_reference, lora_adapter = generation_lora(character, restore_take) if legacy_restore else generation_mix(character, restore_take)
    take_id = take_id or deps.new_id("take")
    if restore_take is not None:
        _validate_take_restoration_configuration(project, restore_take)
    fixed_seed = line.get("manualSeed", line.get("fixedSeed"))
    seed_setting = int(project.get("settings", {}).get("seed", 0) or 0)
    seed = int(restore_take["seed"]) if restore_take is not None else (seed_override if seed_override is not None else (int(fixed_seed) if fixed_seed is not None else (seed_setting if seed_setting else secrets.randbelow(2000000000))))
    output = deps.MEDIA_ROOT / "takes" / deps.safe_segment(line_id) / f"{take_id}.wav"
    replacement_id = deps.new_id("render")
    render_output = output.with_name(f".partial-{take_id}-{replacement_id}.wav")
    render_output.parent.mkdir(parents=True, exist_ok=True)
    started_at = time.perf_counter()
    saved_settings = restore_take.get("settings", {}) if restore_take is not None else {}
    speech_rate, target_duration = line_speech_timing(project, line, restore_take)
    rendered_text, used_global_pronunciation_ids = line_spoken_text(project, line, restore_take)
    project_settings = project.get("settings", {})
    capabilities = deps.model_capabilities_for_selection(project.get("ttsSelection")) or {}
    supports_runtime_cfg = capabilities.get("supportsRuntimeCfg", True)
    effective_cfg = ({key: saved_settings.get(key, line.get(key, project_settings.get(key, default))) for key, default in (("textCfg", 3.0), ("voiceCfg", 5.0), ("captionCfg", 3.0))} if supports_runtime_cfg else {})
    effective_steps = int(capabilities.get("fixedSteps") or saved_settings.get("steps") or project_settings.get("steps", 16))
    sampling_project_settings = project_settings if supports_runtime_cfg else {key: value for key, value in project_settings.items() if key not in {"textCfg", "voiceCfg", "captionCfg", "quality"}}
    try:
        deps.run_irodori(
            text=rendered_text,
            caption=str(restore_take.get("stageDirection", line.get("stageDirection", "")) if restore_take else line.get("stageDirection", "")).strip() or None,
            output=render_output,
            seed=seed,
            ref_wav=reference,
            quality=quality,
            generation_settings={
                **sampling_project_settings,
                "steps": effective_steps,
                **effective_cfg,
                "speechRate": speech_rate,
                "targetDurationSeconds": target_duration,
            },
            should_cancel=should_cancel,
            lora_adapter=lora_adapter,
        )
        if restore_take is not None:
            validate_take_execution(restore_take.get("ttsConfiguration") or {}, deps.last_inference_execution())
        duration_seconds = round(deps.validate_take_wav(render_output), 2)
        render_output.replace(output)
    except Exception:
        render_output.unlink(missing_ok=True)
        raise
    generation_seconds = round(time.perf_counter() - started_at, 2)
    deps.promote_project_pronunciations(project, used_global_pronunciation_ids)
    take = {
        ("lora" if legacy_restore else "loraMix"): lora_reference,
        "id": take_id,
        "characterId": str(line.get("characterId", "")),
        "audioUrl": deps.media_url(output),
        "seed": seed,
        "quality": quality,
        "settings": {
            "speechRate": speech_rate,
            "steps": effective_steps,
            **effective_cfg,
        },
        "stageDirection": restore_take.get("stageDirection", line.get("stageDirection", "")) if restore_take else line.get("stageDirection", ""),
        "renderedText": rendered_text,
        "durationSeconds": duration_seconds,
        "generationSeconds": generation_seconds,
        "createdAt": restore_take.get("createdAt", deps.now_ms()) if restore_take else deps.now_ms(),
    }
    if target_duration is not None:
        take["targetDurationSeconds"] = target_duration
    selection = project.get("ttsSelection")
    if isinstance(selection, dict):
        execution = deps.last_inference_execution()
        take["loraExecution"] = execution.get("lora")
        take["ttsConfiguration"] = {
            "engineCommit": (selection.get("engine") or {}).get("commit"),
            "modelRevision": (selection.get("model") or {}).get("revision"),
            "codecRevision": selection.get("codecRevision"),
            "codecArtifactRepo": (execution.get("codec") or {}).get("repo"),
            "codecArtifactRevision": (execution.get("codec") or {}).get("revision"),
            "codecPrecision": (execution.get("codec") or {}).get("precision"),
            "optimizationProfile": execution.get("optimizationProfile", "upstream-eager"),
            "precision": execution.get("precision", "fp32"),
            "variantId": execution.get("variantId", "pytorch-fp32"),
            "backend": execution.get("backend", "pytorch"),
            "artifactRepo": execution.get("artifactRepo", (selection.get("model") or {}).get("repo")),
            "artifactRevision": execution.get("artifactRevision", (selection.get("model") or {}).get("revision")),
            "route": execution.get("route"),
        }
        take["ttsPerformance"] = {
            "stageTimingsMs": execution.get("stageTimingsMs", {}),
            "fallbackReason": execution.get("fallbackReason"),
            "cache": execution.get("optimizationStats", {}),
            "peakVramBytes": execution.get("peakVramBytes"),
        }
    return take


def _validate_take_restoration_configuration(project: dict[str, Any], take: dict[str, Any]) -> None:
    saved = take.get("ttsConfiguration")
    selected = project.get("ttsSelection")
    if not isinstance(saved, dict) or not isinstance(selected, dict):
        raise HTTPException(status_code=409, detail="保存済みTakeのTTS構成が不足しているため復元できません。")
    validate_take_runtime(saved, deps.selected_tts_runtime())
    current = {
        "engineCommit": (selected.get("engine") or {}).get("commit"),
        "modelRevision": (selected.get("model") or {}).get("revision"),
        "codecRevision": selected.get("codecRevision"),
    }
    if any(saved.get(key) != value for key, value in current.items()):
        raise HTTPException(status_code=409, detail="保存済みTakeと同じモデル・engine revision・Codecを利用できないため復元できません。")


def _auto_render_cancelled(request: deps.GenerateLineRequest, line_id: str) -> Callable[[], bool] | None:
    if not request.interruptible:
        return None
    with deps.AUTO_RENDER_INTERRUPT_LOCK:
        deps.AUTO_RENDER_ACTIVE["lineId"] = line_id
        deps.AUTO_RENDER_INTERRUPT.clear()
    return deps.AUTO_RENDER_INTERRUPT.is_set


def _finish_auto_render(request: deps.GenerateLineRequest, line_id: str) -> None:
    if request.interruptible:
        with deps.AUTO_RENDER_INTERRUPT_LOCK:
            if deps.AUTO_RENDER_ACTIVE["lineId"] == line_id:
                deps.AUTO_RENDER_ACTIVE["lineId"] = None
                deps.AUTO_RENDER_INTERRUPT.clear()


@deps.app.post("/api/lines/auto-render/cancel")
def cancel_auto_render(request: deps.CancelAutoRenderRequest | None = None) -> dict[str, bool]:
    """Interrupt only the current auto-render synthesis so a priority shortcut can run."""
    with deps.AUTO_RENDER_INTERRUPT_LOCK:
        active = deps.AUTO_RENDER_ACTIVE["lineId"]
        matched = request is None or request.lineId is None or request.lineId == active
        if matched and active is not None:
            deps.AUTO_RENDER_INTERRUPT.set()
        return {"cancelled": matched and active is not None}


@deps.app.post("/api/lines/{line_id}/generate", response_model=deps.LineGenerationResponse)
def generate_line(line_id: str, request: deps.GenerateLineRequest) -> dict[str, Any]:
    deps.require_tts_available()
    project = deps.read_project()
    _, line = deps.find_line(project, line_id)
    render_signature = deps.line_render_signature(project, line)
    selected_id = str(line.get("selectedTakeId") or "")
    take_index = next((index for index, item in enumerate(line.get("takes", [])) if item.get("id") == selected_id), None)
    replacing = request.mode == "replace" and take_index is not None
    rollback = deps.take_rollback_copy(line_id, selected_id) if replacing else None
    should_cancel = _auto_render_cancelled(request, line_id)
    try:
        try:
            take = create_line_take(
                project,
                line,
                request.quality,
                take_id=selected_id if replacing else None,
                should_cancel=should_cancel,
                seed_override=request.seed,
            )
        except deps.GenerationCancelled as error:
            if request.interruptible:
                raise HTTPException(status_code=409, detail={"code": "priority_interruption", "message": "優先再生のため自動生成を中断しました。"}) from error
            raise
        with deps.PROJECT_ROOT_LOCK:
            latest = deps.read_project()
            _, latest_line = deps.find_line(latest, line_id)
            if deps.line_render_signature(latest, latest_line) != render_signature:
                deps.discard_generated_take(take)
                raise HTTPException(
                    status_code=409,
                    detail={"code": "render_input_changed", "message": "生成中に発話の内容が変更されました。"},
                )
            latest_index = next(
                (index for index, item in enumerate(latest_line.get("takes", [])) if item.get("id") == selected_id),
                None,
            )
            if replacing and latest_index is not None:
                latest_line["takes"][latest_index] = take
            else:
                latest_line["takes"] = latest_line.get("takes", []) + [take]
            latest_line["selectedTakeId"] = take["id"]
            saved = deps.write_project(latest)
    except Exception:
        deps.finish_take_replacement(rollback, restore=True)
        raise
    else:
        deps.finish_take_replacement(rollback, restore=False)
    finally:
        _finish_auto_render(request, line_id)
    return {"take": take, "projectRevision": saved["revision"]}


@deps.app.post("/api/lines/{line_id}/regenerate", response_model=deps.LineGenerationResponse)
def regenerate_line(line_id: str, request: deps.GenerateLineRequest) -> dict[str, Any]:
    """Replace the selected take in place, preserving its take slot."""
    deps.require_tts_available()
    project = deps.read_project()
    _, line = deps.find_line(project, line_id)
    render_signature = deps.line_render_signature(project, line)
    selected_id = str(request.targetTakeId or line.get("selectedTakeId") or "")
    if request.targetTakeId and line.get("selectedTakeId") not in (None, request.targetTakeId):
        raise HTTPException(status_code=409, detail={"code": "render_input_changed", "message": "上書き対象の選択が変更されました。"})
    take_index = next((index for index, item in enumerate(line.get("takes", [])) if item.get("id") == selected_id), None)
    if take_index is None:
        raise HTTPException(status_code=422, detail="上書きする選択テイクがありません。先に新規生成してください。")
    rollback = deps.take_rollback_copy(line_id, selected_id)
    should_cancel = _auto_render_cancelled(request, line_id)
    try:
        try:
            take = create_line_take(
                project,
                line,
                request.quality,
                take_id=selected_id,
                should_cancel=should_cancel,
                seed_override=request.seed,
            )
        except deps.GenerationCancelled as error:
            if request.interruptible:
                raise HTTPException(status_code=409, detail={"code": "priority_interruption", "message": "優先再生のため自動生成を中断しました。"}) from error
            raise
        with deps.PROJECT_ROOT_LOCK:
            latest = deps.read_project()
            _, latest_line = deps.find_line(latest, line_id)
            if deps.line_render_signature(latest, latest_line) != render_signature:
                deps.discard_generated_take(take)
                raise HTTPException(
                    status_code=409,
                    detail={"code": "render_input_changed", "message": "生成中に発話の内容が変更されました。"},
                )
            latest_index = next(
                (index for index, item in enumerate(latest_line.get("takes", [])) if item.get("id") == selected_id),
                None,
            )
            if latest_index is None:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "render_input_changed", "message": "生成中に選択テイクが変更されました。"},
                )
            if request.targetTakeId and latest_line.get("selectedTakeId") not in (None, request.targetTakeId):
                deps.discard_generated_take(take)
                raise HTTPException(status_code=409, detail={"code": "render_input_changed", "message": "上書き対象の選択が変更されました。"})
            latest_line["takes"][latest_index] = take
            latest_line["selectedTakeId"] = take["id"]
            saved = deps.write_project(latest)
    except Exception:
        deps.finish_take_replacement(rollback, restore=True)
        raise
    else:
        deps.finish_take_replacement(rollback, restore=False)
    finally:
        _finish_auto_render(request, line_id)
    return {"take": take, "projectRevision": saved["revision"]}


@deps.app.delete("/api/lines/{line_id}/takes/{take_id}")
def delete_line_take(line_id: str, take_id: str) -> dict[str, Any]:
    with deps.PROJECT_ROOT_LOCK:
        return _delete_line_take_locked(line_id, take_id)


def _delete_line_take_locked(line_id: str, take_id: str) -> dict[str, Any]:
    project = deps.read_project()
    _, line = deps.find_line(project, line_id)
    takes = line.get("takes", [])
    take_index = next((index for index, item in enumerate(takes) if item.get("id") == take_id), None)
    if take_index is None:
        raise HTTPException(status_code=404, detail="Take not found.")
    take = takes[take_index]
    audio_url = str(take.get("audioUrl", ""))
    if audio_url.startswith("/media/"):
        audio_file = (deps.MEDIA_ROOT / audio_url.removeprefix("/media/")).resolve()
        takes_root = (deps.MEDIA_ROOT / "takes").resolve()
        try:
            audio_file.relative_to(takes_root)
        except ValueError as error:
            raise HTTPException(status_code=500, detail="Take audio path was invalid.") from error
    else:
        audio_file = None
    del takes[take_index]
    if line.get("selectedTakeId") == take_id:
        line["selectedTakeId"] = takes[min(take_index, len(takes) - 1)]["id"] if takes else None
    deps.write_project(project)
    if audio_file is not None:
        try:
            audio_file.unlink(missing_ok=True)
        except OSError:
            pass
    return project


deps.register(
    __name__,
    [
        "clear_all_takes",
        "cleanup_selected_takes",
        "add_cue_member",
        "create_line_take",
        "delete_line",
        "delete_line_take",
        "delete_scene",
        "generate_line",
        "insert_line",
        "mix_cue",
        "regenerate_line",
    ],
)

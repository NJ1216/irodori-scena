from __future__ import annotations

import threading
import hashlib

from server.app_deps import json, os, shutil, Path, Any, quote, HTTPException, Response
from server.registry import deps


def _prepare_tts_when_eager() -> None:
    deps.start_tts_prepare(startup=True)


def _require_workspace_switch_available(message: str) -> None:
    if deps.active_draft_job() or deps.active_export_job() or deps.INFERENCE_SYNTHESIS_LOCK.locked():
        raise HTTPException(status_code=409, detail={"code": "operation_conflict", "message": message})


@deps.app.on_event("startup")
def startup() -> None:
    deps.ensure_data_root()
    deps.ensure_tts_storage()
    project = deps.read_project()
    deps.reconcile_cast_pronunciations(deps.pronunciation_characters(project))
    pronunciation_changed = deps.reconcile_script_pronunciations(project, add_only=True)
    media_changed = deps.reconcile_project_media(project)
    if media_changed or pronunciation_changed:
        deps.write_project(project, project_only=pronunciation_changed and not media_changed)
    deps.cleanup_loaded_project(project)
    _prepare_tts_when_eager()


@deps.app.get("/api/health")
def health() -> dict[str, Any]:
    engine = Path(os.getenv("IRODORI_TTS_ENGINE_DIR", str(deps.ENGINE_DEFAULT))).expanduser()
    schema = json.dumps(deps.app.openapi(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return {
        "ok": True,
        "engine_available": (engine / "infer.py").is_file(),
        "sample_text": deps.VOICE_SAMPLE_TEXT,
        "apiSchemaHash": hashlib.sha256(schema).hexdigest(),
    }


@deps.app.get("/api/project")
def get_project() -> Response:
    return Response(
        content=json.dumps(deps.read_project(), ensure_ascii=False),
        media_type="application/json",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@deps.app.get("/api/project/workspace")
def get_workspace() -> dict[str, Any]:
    return deps.workspace_info()


@deps.app.post("/api/settings/engine-directory")
def choose_engine_directory(request: deps.WorkspaceRequest | None = None) -> dict[str, str]:
    directory = _selected_directory(request, "Irodori-TTS のフォルダを選択")
    if not (directory / "infer.py").is_file():
        raise HTTPException(status_code=422, detail="Irodori-TTS の infer.py があるフォルダを選択してください。")
    return deps.write_engine_directory(str(directory))


@deps.app.get("/api/settings/engine-directory")
def get_engine_directory() -> dict[str, Any]:
    settings = deps.read_connection_settings()
    return {"engineDir": settings["engineDir"], "engineDirVerified": settings["engineDirVerified"]}


@deps.app.post("/api/project/save-workspace")
def save_workspace(request: deps.WorkspaceRequest | None = None) -> dict[str, Any]:
    _require_workspace_switch_available("進行中の生成またはエクスポートが終わってから保存してください。")
    if deps.ACTIVE_PROJECT_PATH is None:
        destination = _selected_project_file(request, "プロジェクトを保存")
        return deps.move_scratch_project_to(destination)
    with deps.PROJECT_ROOT_LOCK:
        deps.write_project(deps.materialize_cast_global_characters(deps.read_project()))
    deps.persist_active_container()
    return {"project": deps.read_project(), "workspace": deps.workspace_info(), "moved": False}


@deps.app.post("/api/project/open-workspace")
def open_workspace(request: deps.WorkspaceRequest | None = None) -> dict[str, Any]:
    _require_workspace_switch_available("進行中の生成またはエクスポートが終わってから読み込んでください。")
    selected = _selected_project_file(request, "開く .scena プロジェクトを選択")
    signature = deps.container_signature(selected)
    requires_upgrade = deps.container_requires_upgrade(selected)
    candidate_root = deps.working_root(selected).with_name(f"{deps.working_root(selected).name}-preflight")
    deps.extract_container(selected, candidate_root)
    try:
        raw = json.loads((candidate_root / "project.json").read_text(encoding="utf-8"))
        deps.StudioProjectModel.model_validate(raw)
        deps.shutdown_inference_worker()
        deps.activate_project_container(selected, prepared_root=candidate_root, expected_signature=signature)
        deps.reset_overlap_preparation()
        if requires_upgrade:
            deps.sync_container(
                selected,
                deps.ACTIVE_PROJECT_ROOT,
                include_derived_audio=False,
                compact=True,
            )
    except Exception as error:
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(status_code=422, detail=f"project.jsonが不正です: {error}") from error
    finally:
        shutil.rmtree(candidate_root, ignore_errors=True)
    deps.clear_script_assistant_summary_cache()
    deps.ensure_data_root()
    deps.begin_history_session()
    with deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        pronunciation_changed = deps.reconcile_script_pronunciations(project, add_only=True)
        media_changed = deps.reconcile_project_media(project)
        if media_changed or pronunciation_changed:
            project = deps.write_project(project, project_only=pronunciation_changed and not media_changed)
    deps.cleanup_loaded_project(project)
    _prepare_tts_when_eager()
    return {
        "project": project,
        "workspace": deps.workspace_info(),
        "globalCastUpdates": deps.global_cast_update_candidates(project),
    }


def _selected_directory(request: deps.WorkspaceRequest | None, prompt: str) -> Path:
    if request is None:
        if os.getenv("SCENA_DESKTOP") == "1":
            raise HTTPException(status_code=422, detail="デスクトップアプリから選択済みフォルダを指定してください。")
        return deps.choose_directory(prompt)
    directory = Path(request.path).expanduser()
    if not directory.is_absolute() or not directory.is_dir():
        raise HTTPException(status_code=422, detail="選択されたフォルダを開けませんでした。")
    return directory.resolve()


def _selected_project_file(request: deps.WorkspaceRequest | None, prompt: str) -> Path:
    if request is None:
        raise HTTPException(status_code=422, detail=f"{prompt}には選択済み.scenaファイルを指定してください。")
    path = Path(request.path).expanduser()
    if not path.is_absolute() or path.suffix.lower() != ".scena":
        raise HTTPException(status_code=422, detail=".scenaファイルを指定してください。")
    return path.resolve()


@deps.app.post("/api/project/apply-global-cast-updates")
def apply_global_cast_updates(request: deps.GlobalCastUpdatesRequest) -> dict[str, Any]:
    return deps.apply_global_cast_updates(request.character_ids)


@deps.app.post("/api/project/new")
def create_new_project() -> dict[str, Any]:
    """Start a clean scratch project without deleting a saved project folder."""
    _require_workspace_switch_available("進行中の生成またはエクスポートが終わってから新規作成してください。")
    deps.shutdown_inference_worker()
    deps.clear_script_assistant_summary_cache()
    deps.activate_project_root(deps.default_workspace_root())
    deps.ensure_data_root()
    scratch_media = deps.MEDIA_ROOT.resolve()
    staged_media = scratch_media.with_name(f".{scratch_media.name}-{deps.new_id('cleanup')}")
    if scratch_media.exists():
        scratch_media.replace(staged_media)
    deps.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    deps.write_project(deps.apply_tts_defaults(deps.default_project()))
    deps.begin_history_session()
    deps.reset_session_usage()

    def finish_transition() -> None:
        shutil.rmtree(staged_media, ignore_errors=True)
        _prepare_tts_when_eager()

    threading.Thread(target=finish_transition, daemon=True).start()
    return {"project": deps.read_project(), "workspace": deps.workspace_info()}


@deps.app.post("/api/project/backup")
def create_project_backup(request: deps.WorkspaceRequest) -> dict[str, Any]:
    if deps.active_draft_job() or deps.active_export_job():
        raise HTTPException(
            status_code=409, detail="進行中の生成またはエクスポートが終わってからバックアップしてください。"
        )
    return deps.backup_project(request.path)


@deps.app.post("/api/project/optimize")
def optimize_project() -> dict[str, Any]:
    _require_workspace_switch_available("進行中の生成またはエクスポートが終わってから最適化保存してください。")
    with deps.PROJECT_ROOT_LOCK:
        container = deps.ACTIVE_PROJECT_PATH
        if container is None:
            raise HTTPException(status_code=409, detail="先にプロジェクトを保存してください。")
        before = container.stat().st_size
        project = deps.read_project()
        if deps.reconcile_project_media(project):
            project = deps.write_project(project)
        deps.cleanup_loaded_project(project)
        return {"project": deps.read_project(), "beforeBytes": before, "afterBytes": container.stat().st_size}


@deps.app.get("/api/project/optimization-status")
def project_optimization_status() -> dict[str, bool]:
    with deps.PROJECT_ROOT_LOCK:
        if deps.ACTIVE_PROJECT_PATH is None:
            return {"available": False}
        return {"available": deps.project_optimization_available(deps.read_project())}


def _script_text(project: dict[str, Any]) -> str:
    names = {str(item.get("id", "")): str(item.get("name", "")) for item in project.get("characters", [])}
    contexts = project.get("scriptCastContexts", {})
    rows: list[str] = ["【キャスト】"]
    used_ids = dict.fromkeys(
        str(line.get("characterId", ""))
        for scene in project.get("scenes", [])
        for line in scene.get("lines", [])
        if line.get("enabled") is not False and str(line.get("text", "")).strip()
    )
    for character_id in used_ids:
        context = contexts.get(character_id, {}) if isinstance(contexts, dict) else {}
        rows.append(
            f"{names.get(character_id, character_id)}｜役割: {str(context.get('role', '')).strip() or '未設定'}"
        )
        description = str(context.get("description") or context.get("setting", "")).strip()
        if description:
            rows.append(f"  人物紹介: {description}")
    number = 0
    for scene in project.get("scenes", []):
        enabled_lines = [
            line
            for line in scene.get("lines", [])
            if line.get("enabled") is not False and str(line.get("text", "")).strip()
        ]
        if not enabled_lines:
            continue
        rows.extend(("", f"【{str(scene.get('title', '')).strip() or 'シーン'}】"))
        for line in enabled_lines:
            number += 1
            rows.append(f"{number:04d} {names.get(str(line.get('characterId', '')), '未設定')}")
            direction = str(line.get("stageDirection", "")).strip()
            if direction:
                rows.append(f"（{direction}）")
            rows.append(str(line.get("text", "")).strip())
    return "\n".join(rows).rstrip() + "\n"


@deps.app.get("/api/project/script.txt")
def download_script_text() -> Response:
    project = deps.read_project()
    filename = f"{deps.safe_download_name(str(project.get('title', '')), 'irodori SCENA')}.txt"
    return Response(
        content=_script_text(project),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}"},
    )


@deps.app.post("/api/project/import-script")
def import_script(request: deps.ScriptImportRequest) -> dict[str, Any]:
    if deps.active_draft_job() or deps.active_export_job():
        raise HTTPException(
            status_code=409, detail="進行中の生成またはエクスポートが終わってから台本を読み込んでください。"
        )
    with deps.PROJECT_ROOT_LOCK:
        return _import_script_locked(request)


def _import_script_locked(request: deps.ScriptImportRequest) -> dict[str, Any]:
    project = deps.read_project()
    character_ids = {str(character.get("id", "")) for character in project.get("characters", [])}
    invalid_ids = {line.character_id for line in request.lines} - character_ids
    if invalid_ids:
        raise HTTPException(status_code=422, detail="登録済みでないキャストが選択されています。")
    lines = [
        {
            "id": deps.new_id("line"),
            "characterId": line.character_id,
            "text": line.text.strip(),
            "stageDirection": "",
            "takes": [],
            "selectedTakeId": None,
        }
        for line in request.lines
        if line.text.strip()
    ]
    if not lines:
        raise HTTPException(status_code=422, detail="読み込める台詞がありません。")
    empty_scene = next((scene for scene in project.get("scenes", []) if not scene.get("lines")), None)
    if empty_scene is None:
        empty_scene = {"id": deps.new_id("scene"), "title": "読み込み台本", "lines": []}
        project.setdefault("scenes", []).append(empty_scene)
    empty_scene.setdefault("lines", []).extend(lines)
    return deps.write_project(project)


@deps.app.put("/api/project")
def update_project(update: deps.ProjectUpdate) -> dict[str, Any]:
    project = update.project.model_dump(by_alias=True, exclude_none=True)
    if not isinstance(project.get("scenes"), list) or not isinstance(project.get("characters"), list):
        raise HTTPException(status_code=422, detail="Project needs scenes and characters arrays.")
    if deps.active_export_job():
        current = deps.read_project()
        current_lines = {
            str(line.get("id", "")): line
            for scene in current.get("scenes", [])
            for line in scene.get("lines", [])
            if isinstance(line, dict)
        }
        for scene in project.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            for line in scene.get("lines", []):
                if not isinstance(line, dict):
                    continue
                previous = current_lines.get(str(line.get("id", "")))
                if previous is None:
                    continue
                render_inputs_changed = any(
                    (
                        line.get(key) != previous.get(key)
                        for key in ("text", "stageDirection", "characterId", "speechRate")
                    )
                )
                line["takes"] = previous.get("takes", [])
                line["selectedTakeId"] = None if render_inputs_changed else previous.get("selectedTakeId")
    expected_revision = update.base_revision
    if expected_revision is None:
        expected_revision = int(project.get("revision", 0))
    return deps.write_project(project, expected_revision=expected_revision)


@deps.app.patch("/api/lines/{line_id}/character")
def change_line_character(line_id: str, request: deps.ChangeLineCharacterRequest) -> dict[str, Any]:
    with deps.PROJECT_ROOT_LOCK:
        return _change_line_character_locked(line_id, request)


def _change_line_character_locked(line_id: str, request: deps.ChangeLineCharacterRequest) -> dict[str, Any]:
    project = deps.read_project()
    deps.find_character(project, request.character_id)
    scene, line = deps.find_line(project, line_id)
    cue = deps.cue_for_line(scene, line_id)
    if len(cue) > 1 and any(
        item is not line and str(item.get("characterId", "")) == request.character_id for item in cue
    ):
        raise HTTPException(status_code=409, detail="同じ同時発話内でキャストを重複させることはできません。")
    previous_character_id = str(line.get("characterId", ""))
    if previous_character_id != request.character_id:
        if previous_character_id:
            _normalize_takes_character_ids(line, previous_character_id)
        line["characterId"] = request.character_id
        line["selectedTakeId"] = _find_latest_take_for_character(line, request.character_id)
        deps.write_project(project)
    return project


def _find_latest_take_for_character(line: dict[str, Any], character_id: str) -> str | None:
    for item in reversed(line.get("takes", [])):
        if str(item.get("characterId", "")) == str(character_id):
            return str(item.get("id", "")) or None
    return None


def _normalize_takes_character_ids(line: dict[str, Any], character_id: str) -> None:
    if not character_id:
        return
    for item in line.get("takes", []):
        if str(item.get("characterId", "")) == "":
            item["characterId"] = character_id


def _merge_script_cast_contexts(contexts: dict[str, Any], mappings: list[Any]) -> dict[str, dict[str, str]]:
    """Move contexts from one immutable pre-switch snapshot."""
    source_ids = {mapping.from_character_id for mapping in mappings}
    result = {key: dict(value) for key, value in contexts.items() if key not in source_ids and isinstance(value, dict)}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        value = contexts.get(mapping.from_character_id)
        if isinstance(value, dict):
            grouped.setdefault(mapping.to_character_id, []).append(value)
    for target_id, values in grouped.items():
        role_parts: list[str] = []
        description_parts: list[str] = []
        for value in values:
            for key, output in (("role", role_parts), ("description", description_parts)):
                text = str(value.get(key, "")).strip()
                if text and text not in output:
                    output.append(text)
            legacy_description = str(value.get("setting", "")).strip()
            if legacy_description and legacy_description not in description_parts:
                description_parts.append(legacy_description)
        result[target_id] = {"role": "\n".join(role_parts), "description": "\n".join(description_parts)}
    return result


@deps.app.post("/api/project/switch-characters")
def switch_characters(request: deps.BulkSwitchCharactersRequest) -> dict[str, Any]:
    """Apply swaps and merges simultaneously from the original speaker IDs."""
    with deps.PROJECT_ROOT_LOCK:
        return _switch_characters_locked(request)


def _switch_characters_locked(request: deps.BulkSwitchCharactersRequest) -> dict[str, Any]:
    project = deps.read_project()
    mapping_by_source: dict[str, str] = {}
    for mapping in request.mappings:
        if mapping.from_character_id in mapping_by_source:
            raise HTTPException(status_code=422, detail="同じ切り替え元を複数回指定できません。")
        deps.find_character(project, mapping.from_character_id)
        deps.find_character(project, mapping.to_character_id)
        mapping_by_source[mapping.from_character_id] = mapping.to_character_id
    invalidated_lines = 0
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []):
            source_id = str(line.get("characterId", ""))
            target_id = mapping_by_source.get(source_id)
            if target_id is None or target_id == source_id:
                continue
            _normalize_takes_character_ids(line, source_id)
            line["characterId"] = target_id
            # Old immutable takes and WAVs remain available, but a cast switch
            # always requires an explicit new selection/generation.
            line["selectedTakeId"] = None
            invalidated_lines += 1
    contexts = project.get("scriptCastContexts")
    if isinstance(contexts, dict):
        project["scriptCastContexts"] = _merge_script_cast_contexts(contexts, request.mappings)
    deps.write_project(project)
    return {"project": project, "invalidatedLines": invalidated_lines}


deps.register(
    __name__,
    [
        "change_line_character",
        "create_project_backup",
        "create_new_project",
        "download_script_text",
        "get_engine_directory",
        "get_project",
        "get_workspace",
        "health",
        "import_script",
        "open_workspace",
        "optimize_project",
        "project_optimization_status",
        "save_workspace",
        "switch_characters",
        "startup",
        "update_project",
    ],
)

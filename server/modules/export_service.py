from __future__ import annotations

from copy import deepcopy

from server.app_deps import json, Path, Any, Callable, HTTPException
from server.registry import deps
from server.modules.job_publication import public_job
from server.modules.line_synthesis_inputs import line_speech_timing, line_spoken_text
from server.modules.pronunciation_dictionary import dictionary_transaction
from server.modules.export_estimates import estimated_draft_seconds as estimated_draft_seconds
from server.modules.export_audio import join_wav_files as join_wav_files


def active_draft_job(*, excluding_job_id: str | None = None) -> bool:
    with deps.DRAFT_JOBS_LOCK:
        return any(
            job_id != excluding_job_id and job.get("status") in {"planning", "generating"}
            for job_id, job in deps.DRAFT_JOBS.items()
        )


def draft_cancel_requested(job_id: str) -> bool:
    with deps.DRAFT_JOBS_LOCK:
        return bool(deps.DRAFT_JOBS.get(job_id, {}).get("cancelRequested"))


def ensure_draft_not_cancelled(job_id: str) -> None:
    if draft_cancel_requested(job_id):
        raise deps.GenerationCancelled("台本生成をキャンセルしました。")


def active_export_job() -> bool:
    with deps.EXPORT_JOBS_LOCK:
        return any(
            (
                job.get("status") in {"preparing", "generating", "aligning", "writing"}
                for job in deps.EXPORT_JOBS.values()
            )
        )


def require_tts_available(*, excluding_draft_job_id: str | None = None) -> None:
    if active_draft_job(excluding_job_id=excluding_draft_job_id):
        raise HTTPException(status_code=409, detail="AI台本を生成中です。完了後に音声合成を再開できます。")
    if active_export_job():
        raise HTTPException(status_code=409, detail="まとめてエクスポート中です。完了後に音声合成を再開できます。")
    runtime = deps.selected_tts_runtime()
    if runtime is None:
        raise HTTPException(
            status_code=409,
            detail="使用するIrodori-TTSモデルがありません。同じrevisionを追加するか、既定モデルを選択してください。",
        )
    if runtime.get("model") is None:
        raise HTTPException(
            status_code=409,
            detail="使用する音声モデルがありません。同じrevisionを追加するか、既定モデルを選択してください。",
        )


def selected_take_record(line: dict[str, Any]) -> dict[str, Any] | None:
    selected_id = line.get("selectedTakeId")
    return next((item for item in line.get("takes", []) if item.get("id") == selected_id), None)


def take_audio_path(take: dict[str, Any]) -> Path:
    audio_url = deps.canonical_project_media_url(str(take.get("audioUrl", "")))
    if not audio_url.startswith("/media/"):
        raise RuntimeError("Selected take has no managed audio URL.")
    candidate = (deps.MEDIA_ROOT / audio_url.removeprefix("/media/")).resolve()
    try:
        candidate.relative_to(deps.MEDIA_ROOT.resolve())
    except ValueError as error:
        raise RuntimeError("Selected take audio path was invalid.") from error
    if not candidate.is_file():
        raise RuntimeError("Selected take WAV is missing.")
    return candidate


def public_export_job(job: dict[str, Any], *, after_update: int = 0) -> dict[str, Any]:
    # The caller holds EXPORT_JOBS_LOCK across both detached copies.
    public = public_job(job, {"lineUpdates"})
    public["lineUpdates"] = deepcopy([
        update for update in job.get("lineUpdates", []) if int(update.get("version", 0)) > after_update
    ])
    return public


def update_export_job(job_id: str, **patch: Any) -> None:
    if "status" in patch:
        patch.setdefault("phase", patch["status"])
    public = None
    with deps.EXPORT_JOBS_LOCK:
        if job_id in deps.EXPORT_JOBS:
            deps.EXPORT_JOBS[job_id].update(patch)
            public = public_export_job(deps.EXPORT_JOBS[job_id])
    if public is not None:
        deps.PROGRESS_EVENTS.observe(public)


def record_export_line_update(
    job_id: str, *, scene_id: str, line: dict[str, Any], completed_lines: int, generated_lines: int
) -> None:
    """Atomically publish the finished line for UI-side incremental updates."""
    public = None
    with deps.EXPORT_JOBS_LOCK:
        job = deps.EXPORT_JOBS.get(job_id)
        if job is None:
            return
        version = int(job.get("updateVersion", 0)) + 1
        job["updateVersion"] = version
        job.setdefault("lineUpdates", []).append({"version": version, "sceneId": scene_id, "line": line})
        job["completedLines"] = completed_lines
        job["generatedLines"] = generated_lines
        public = public_export_job(job)
    deps.PROGRESS_EVENTS.observe(public)


def export_cancel_requested(job_id: str) -> bool:
    with deps.EXPORT_JOBS_LOCK:
        return bool(deps.EXPORT_JOBS.get(job_id, {}).get("cancelRequested"))


def find_line_record(project: dict[str, Any], line_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for scene in project.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        for line in scene.get("lines", []):
            if isinstance(line, dict) and line.get("id") == line_id:
                return (scene, line)
    return None


def line_render_signature(project: dict[str, Any], line: dict[str, Any]) -> str:
    settings = project.get("settings", {})
    speech_rate, target_duration = line_speech_timing(project, line)
    rendered_text, _ = line_spoken_text(project, line)
    character = next((item for item in project.get("characters", []) if item.get("id") == line.get("characterId")), {})
    selection = project.get("ttsSelection") or {}
    capabilities = deps.model_capabilities_for_selection(selection) or {}
    supports_runtime_cfg = capabilities.get("supportsRuntimeCfg", True)
    fixed_steps = capabilities.get("fixedSteps")
    sampling = {
        "quality": settings.get("quality", "fast"),
        "steps": fixed_steps or settings.get("steps", 16),
    }
    if supports_runtime_cfg:
        sampling.update({
            "textCfg": line.get("textCfg", settings.get("textCfg", 3.0)),
            "voiceCfg": line.get("voiceCfg", settings.get("voiceCfg", 5.0)),
            "captionCfg": line.get("captionCfg", settings.get("captionCfg", 3.0)),
        })
    else:
        sampling.pop("quality", None)
    return json.dumps(
        {
            "characterId": line.get("characterId"),
            "text": line.get("text"),
            "renderedText": rendered_text,
            "stageDirection": line.get("stageDirection"),
            "speechRate": speech_rate,
            "targetDurationSeconds": target_duration,
            "reference": {key: character.get(key) for key in ("referenceFile", "referenceVersion", "audioHash")},
            "lora": character.get("lora"),
            "loraMix": character.get("loraMix"),
            "sampling": sampling,
            "ttsSelection": {
                "engineCommit": (selection.get("engine") or {}).get("commit"),
                "modelRevision": (selection.get("model") or {}).get("revision"),
                "codecRevision": selection.get("codecRevision"),
            },
            "seed": line.get("manualSeed", line.get("fixedSeed", settings.get("seed", 0))),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def selected_take_is_available(line: dict[str, Any]) -> bool:
    take = selected_take_record(line)
    if take is None:
        return False
    try:
        take_audio_path(take)
    except RuntimeError:
        return False
    return True


@dictionary_transaction
def _commit_export_take(line_id, signature, generated, before_dictionary, take, missing_take, should_cancel):
    with deps.PROJECT_ROOT_LOCK:
        if should_cancel():
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
        latest = deps.read_project()
        record = find_line_record(latest, line_id)
        if record is None or line_render_signature(latest, record[1]) != signature:
            return None
        scene, line = record
        _, rendered_line = deps.find_line(generated, line_id)
        if line.get("selectedTakeId") != rendered_line.get("selectedTakeId"):
            return None
        if missing_take and not any(item.get("id") == missing_take.get("id") for item in line.get("takes", [])):
            return None
        deps.merge_generated_pronunciations(latest, before_dictionary, generated)
        if missing_take:
            line["takes"] = [take if item.get("id") == missing_take.get("id") else item for item in line.get("takes", [])]
        else:
            line["takes"] = line.get("takes", []) + [take]
        line["selectedTakeId"] = take["id"]
        deps.write_project(latest)
        return (latest, scene, line, True)


def ensure_export_take(
    line_id: str, quality: str, *, should_cancel: Callable[[], bool]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    """Render the latest version of a line, retrying if it is edited mid-render."""
    for _ in range(3):
        if should_cancel():
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
        project = deps.read_project()
        record = find_line_record(project, line_id)
        if record is None:
            raise RuntimeError("Dialogue line was removed during export.")
        scene, line = record
        if selected_take_is_available(line):
            return (project, scene, line, False)
        signature = line_render_signature(project, line)
        before_dictionary = deepcopy(project.get("pronunciationDictionary", []))
        # The Irodori runtime lives in a persistent worker.  It cannot safely
        # interrupt its synchronous synthesis call, so cancelling a batch
        # waits for this one line rather than terminating (and unloading) the
        # worker.  The completed, uncommitted WAV is discarded below.
        missing_take = selected_take_record(line)
        take = deps.create_line_take(
            project, line,
            str(missing_take.get("quality", project.get("settings", {}).get("quality", quality))) if missing_take else str(project.get("settings", {}).get("quality", quality)),
            take_id=str(missing_take.get("id")) if missing_take else None,
            seed_override=int(missing_take["seed"]) if missing_take and missing_take.get("seed") is not None else None,
            restore_take=missing_take,
        )
        try:
            if should_cancel():
                raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
            committed = _commit_export_take(line_id, signature, project, before_dictionary, take, missing_take, should_cancel)
        except deps.GenerationCancelled:
            deps.discard_generated_take(take)
            raise
        if committed is not None:
            return committed
        deps.discard_generated_take(take)
    raise RuntimeError("発話行が生成中に繰り返し編集されたため、再生成を完了できませんでした。")


def export_spoken_lines(project: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (scene, line)
        for scene in project.get("scenes", [])
        if isinstance(scene, dict)
        for line in scene.get("lines", [])
        if isinstance(line, dict) and line.get("enabled") is not False and str(line.get("text", "")).strip()
    ]


def _prepare_export_lines(job_id: str, project: dict[str, Any], quality: str) -> int:
    generated_lines = 0
    current_lines = export_spoken_lines(project)
    if not current_lines:
        raise RuntimeError("エクスポートする本文のある発話行がありません。")
    for index, (_, initial_line) in enumerate(current_lines):
        if export_cancel_requested(job_id):
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
        if selected_take_is_available(initial_line):
            continue
        update_export_job(
            job_id,
            status="generating",
            totalLines=len(current_lines),
            completedLines=index,
            currentLine=index + 1,
            currentLineId=str(initial_line.get("id", "")),
            message=f"発話行 {index + 1}/{len(current_lines)} を準備しています…",
        )
        _, scene, line, generated = ensure_export_take(
            str(initial_line.get("id", "")), quality, should_cancel=lambda: export_cancel_requested(job_id)
        )
        generated_lines += int(generated)
        record_export_line_update(
            job_id,
            scene_id=str(scene.get("id", "")),
            line=line,
            completed_lines=index + 1,
            generated_lines=generated_lines,
        )
    update_export_job(
        job_id,
        completedLines=len(current_lines),
        currentLine=len(current_lines),
        currentLineId=None,
        message="すべての発話行を準備しました。最終確認へ進みます…",
    )
    return generated_lines


def _complete_unjoined_export(job_id: str, project: dict[str, Any], generated_lines: int) -> None:
    prepared_lines = export_spoken_lines(project)
    update_export_job(
        job_id,
        status="completed",
        currentLine=len(prepared_lines),
        currentLineId=None,
        completedLines=len(prepared_lines),
        generatedLines=generated_lines,
        message="未生成の発話行をすべて自動生成しました。",
        completedAt=deps.now_ms(),
    )


def _individual_export(job_id: str, final_project: dict[str, Any], generated_lines: int) -> None:
    lines = export_spoken_lines(final_project)
    names = {str(item.get("id", "")): str(item.get("name", "キャスト")) for item in final_project.get("characters", [])}
    files = []
    for index, (_, line) in enumerate(lines, 1):
        if export_cancel_requested(job_id):
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
        cast_name = deps.safe_download_name(names.get(str(line.get("characterId", "")), "キャスト"), "キャスト")
        source = take_audio_path(selected_take_record(line) or {})
        files.append(
            {
                "localPath": str(source.resolve()),
                "audioUrl": deps.media_url(source),
                "fileName": f"{index:04d}_{cast_name}.wav",
            }
        )
    update_export_job(
        job_id,
        status="completed",
        currentLineId=None,
        completedLines=len(lines),
        generatedLines=generated_lines,
        message="保存するWAVを台本順に準備しました。",
        files=files,
        completedAt=deps.now_ms(),
    )


def run_export_job(job_id: str) -> None:
    try:
        project = deps.read_project()
        if not export_spoken_lines(project):
            raise RuntimeError("エクスポートする本文のある発話行がありません。")
        with deps.EXPORT_JOBS_LOCK:
            job = dict(deps.EXPORT_JOBS.get(job_id, {}))
        mode = str(job.get("mode", "prepare"))
        request = dict(job.get("request", {}))
        needs_audio = mode == "prepare" or any(item in {"wav", "srt", "lab"} for item in request.get("formats", []))
        quality = str(project.get("settings", {}).get("quality", "fast"))
        generated_lines = _prepare_export_lines(job_id, project, quality) if needs_audio else 0
        final_project = deps.read_project() if needs_audio else project
        if export_cancel_requested(job_id):
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
        if mode == "prepare":
            _complete_unjoined_export(job_id, final_project, generated_lines)
        else:
            aligning = "lab" in request.get("formats", [])
            phase = "aligning" if aligning else "writing"
            alignment_total = len(export_spoken_lines(final_project)) if aligning else 0
            update_export_job(
                job_id,
                status=phase,
                phase=phase,
                alignmentCompletedLines=0,
                alignmentTotalLines=alignment_total,
                message=f"口形LABを解析しています… 0 / {alignment_total} 行"
                if aligning
                else "成果物をエクスポートしています…",
            )
            destination, count, lab_failures = deps.export_bundle(job_id, final_project, request)
            final_status = "completed_with_warnings" if lab_failures else "completed"
            update_export_job(
                job_id,
                status=final_status,
                phase=final_status,
                currentLineId=None,
                completedLines=len(export_spoken_lines(final_project)),
                generatedLines=generated_lines,
                destinationPath=destination,
                artifactCount=count,
                labFailures=lab_failures,
                message="一部の口パクLABを生成できませんでした。" if lab_failures else "エクスポートが完了しました。",
                completedAt=deps.now_ms(),
            )
    except deps.GenerationCancelled:
        update_export_job(
            job_id,
            status="cancelled",
            phase="cancelled",
            message="エクスポートをキャンセルしました。生成済みの行は台本に残っています。",
            completedAt=deps.now_ms(),
        )
    except Exception as error:
        update_export_job(
            job_id,
            status="failed",
            phase="failed",
            message="まとめてエクスポートが途中で止まりました。",
            error=str(error),
            completedAt=deps.now_ms(),
        )


deps.register(
    __name__,
    [
        "active_draft_job",
        "active_export_job",
        "draft_cancel_requested",
        "ensure_draft_not_cancelled",
        "ensure_export_take",
        "estimated_draft_seconds",
        "export_cancel_requested",
        "export_spoken_lines",
        "find_line_record",
        "join_wav_files",
        "line_render_signature",
        "public_export_job",
        "record_export_line_update",
        "require_tts_available",
        "run_export_job",
        "selected_take_is_available",
        "selected_take_record",
        "take_audio_path",
        "update_export_job",
    ],
)

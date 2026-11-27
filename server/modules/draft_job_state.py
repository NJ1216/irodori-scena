from __future__ import annotations

from server.app_deps import Any, shutil
from server.registry import deps
from server.modules.job_publication import public_job


class DraftProjectChanged(RuntimeError):
    code = "draft_project_changed"


def _script_is_empty(scenes: list[dict[str, Any]]) -> bool:
    """Return true only when every existing dialogue body is blank."""
    return not any(
        str(line.get("text", "")).strip()
        for scene in scenes
        for line in scene.get("lines", [])
        if isinstance(line, dict)
    )


def _stage_line_takes(scenes: list[dict[str, Any]]) -> tuple[Any, list[tuple[Any, Any]]]:
    """Move replaced take directories aside so a failed save can restore them."""
    sources = []
    for scene in scenes:
        for line in scene.get("lines", []):
            line_id = str(line.get("id", "")) if isinstance(line, dict) else ""
            if not line_id:
                continue
            source = deps.MEDIA_ROOT / "takes" / deps.safe_segment(line_id)
            if source.exists():
                sources.append(source)
    if not sources:
        return None, []
    cleanup = deps.MEDIA_ROOT / ".cleanup" / deps.new_id("draft")
    cleanup.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for source in sources:
            destination = cleanup / source.name
            source.replace(destination)
            staged.append((source, destination))
    except Exception:
        for source, destination in reversed(staged):
            destination.replace(source)
        shutil.rmtree(cleanup, ignore_errors=True)
        raise
    return cleanup, staged


def _restore_line_takes(cleanup: Any, staged: list[tuple[Any, Any]]) -> None:
    for source, destination in reversed(staged):
        source.parent.mkdir(parents=True, exist_ok=True)
        destination.replace(source)
    if cleanup is not None:
        shutil.rmtree(cleanup, ignore_errors=True)


def public_draft_job(job: dict[str, Any]) -> dict[str, Any]:
    internal = {
        "request", "characters", "plan", "continuity", "hardwareName", "detectedMemoryGiB",
        "tokenBudget", "maxChunkCharacters",
        "selectedContext", "initialDialogueBatchSize", "maximumDialogueBatchSize",
        "adaptiveLongForm", "plannedOutputTokenLimit",
        "plannedMaxChunkCharacters",
        "usedDialogueBatchSizes", "retryInputTokens", "developmentAcceptance",
        "dialogueBatchShrinkReasons", "dialogueBatchHistory", "estimatedResentInputTokensSaved",
        "benchmarkRequiredSourceSchema", "benchmarkSeed",
        "_projectRoot", "_projectId", "_saveCommitted",
    }
    return public_job(job, internal)


def update_draft_job(job_id: str, **patch: Any) -> None:
    public = None
    with deps.DRAFT_JOBS_LOCK:
        if job_id in deps.DRAFT_JOBS:
            deps.DRAFT_JOBS[job_id].update(patch)
            if patch.get("status") in {"completed", "failed", "cancelled"}:
                deps.finish_llm_operation(job_id, patch["status"])
            public = public_draft_job(deps.DRAFT_JOBS[job_id])
    if public is not None:
        deps.PROGRESS_EVENTS.observe(public)


def record_draft_llm_usage(job_id: str | None, usage: Any, *, input_estimate: int = 0,
                           output_text: str = "", provider: str = "", model: str = "", failed: bool = False) -> None:
    """Accumulate detailed usage while retaining the legacy total fields."""
    if not job_id:
        deps.record_llm_call(operation_id=None, usage=usage, input_estimate=input_estimate,
                             output_text=output_text, provider=provider, model=model, failed=failed)
        return
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is None:
            return
        call = deps.record_llm_call(operation_id=job_id, usage=usage, input_estimate=input_estimate,
                                    output_text=output_text, provider=provider or job.get("provider", ""),
                                    model=model or job.get("model", ""), failed=failed)
        if usage is None:
            job["tokenUsageAvailable"] = False
        elif job.get("tokenUsageAvailable", True):
            job["usedTokens"] = int(job.get("usedTokens", 0)) + int(call["totalTokens"])
        current = next((item for item in deps.session_usage()["history"] if item["id"] == job_id), None)
        if current:
            job["tokenUsage"] = current["usage"]
            job["tokenUsageClassification"] = current["classification"]


def add_draft_text_corrections(job_id: str, count: int) -> None:
    """Record accepted typo corrections after a chapter has fully validated."""
    if count <= 0:
        return
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is not None:
            job["performanceTextCorrections"] = int(job.get("performanceTextCorrections", 0)) + count


def advance_draft_progress(
    job_id: str, *, overall_progress: float | None = None, generated_characters: int | None = None
) -> None:
    """Publish only forward-moving author-facing progress values."""
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is None:
            return
        if generated_characters is not None:
            job["generatedCharacters"] = max(int(job.get("generatedCharacters", 0)), max(0, int(generated_characters)))
        if overall_progress is not None:
            job["overallProgress"] = max(
                float(job.get("overallProgress", 0.0)), min(100.0, max(0.0, float(overall_progress)))
            )
        public = public_draft_job(job)
    deps.PROGRESS_EVENTS.observe(public)


def begin_draft_llm_call(job_id: str, *, phase: str, message: str, **patch: Any) -> int:
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS[job_id]
        call_number = int(job.get("llmCallCount", 0)) + 1
        job.update(
            {
                "llmCallCount": call_number,
                "phase": phase,
                "message": message,
                "receivedCharacters": 0,
                "receivedRecords": 0,
                "estimatedGeneratedCharacters": None,
                **patch,
            }
        )
        public = public_draft_job(job)
    deps.PROGRESS_EVENTS.observe(public)
    return call_number


def append_directed_draft(
    job_id: str, *, title: str, chunks: list[dict[str, Any]], script_cast_contexts: dict[str, Any]
) -> None:
    """Persist a fully directed draft in one transaction-like project write."""
    scenes = [scene for chunk in chunks for scene in chunk["scenes"]]
    with deps.PROJECT_ROOT_LOCK, deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS[job_id]
        if job.get("cancelRequested"):
            raise deps.GenerationCancelled("台本生成をキャンセルしました。")
        project = deps.read_project()
        if (job.get("_projectRoot") and job["_projectRoot"] != str(deps.ACTIVE_PROJECT_ROOT)) or (
            job.get("_projectId") and job["_projectId"] != project.get("id")
        ):
            raise DraftProjectChanged("生成開始時と異なるプロジェクトのため保存を停止しました。")
        existing_scenes = project.get("scenes", [])
        replace_empty_script = bool(scenes) and _script_is_empty(existing_scenes)
        cleanup, staged_takes = _stage_line_takes(existing_scenes) if replace_empty_script else (None, [])
        project["title"] = title
        project["scenes"] = scenes if replace_empty_script else existing_scenes + scenes
        project["scriptCastContexts"] = script_cast_contexts
        try:
            deps.write_project(project)
        except Exception:
            _restore_line_takes(cleanup, staged_takes)
            raise
        if cleanup is not None:
            shutil.rmtree(cleanup, ignore_errors=True)
        job["_saveCommitted"] = True
        job["appendedSceneIds"] = [str(scene.get("id", "")) for scene in scenes]
        job["chunks"] = [
            {
                "index": index + 1,
                "title": str(chunk["scenes"][0].get("title", "Scene")),
                "spokenCharacters": int(chunk["spoken"]),
                "estimatedSeconds": deps.estimated_draft_seconds(chunk["scenes"]),
                "discardedDuplicates": int(chunk["discarded_duplicates"]),
            }
            for index, chunk in enumerate(chunks)
        ]
        job["completedChunks"] = len(chunks)
        job["appendedLines"] = sum((len(scene.get("lines", [])) for scene in scenes))
        job["appendedCueCount"] = sum(
            1 for scene in scenes for group in deps.cue_groups(scene.get("lines", [])) if len(group) > 1 and deps.cue_key(group[0])
        )
        job["estimatedSeconds"] = round(sum((float(item["estimatedSeconds"]) for item in job["chunks"])), 1)


def rollback_cancelled_draft(job_id: str) -> None:
    """Remove every scene written by a cancelled draft without touching user work."""
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is None:
            return
        scene_ids = set(job.get("appendedSceneIds", []))
        generated_title = str(job.get("title", ""))
        previous_title = str(job.get("previousTitle", ""))
    if scene_ids:
        with deps.PROJECT_ROOT_LOCK:
            project = deps.read_project()
            project["scenes"] = [scene for scene in project.get("scenes", []) if str(scene.get("id", "")) not in scene_ids]
            if generated_title and project.get("title") == generated_title:
                project["title"] = previous_title
            deps.write_project(project)
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is not None:
            job.update(
                {
                    "chunks": [],
                    "completedChunks": 0,
                    "appendedLines": 0,
                    "appendedCueCount": 0,
                    "estimatedSeconds": 0,
                    "acceptedCharactersTotal": 0,
                    "performanceTextCorrections": 0,
                    "appendedSceneIds": [],
                }
            )


deps.register(
    __name__,
    [
        "add_draft_text_corrections",
        "advance_draft_progress",
        "append_directed_draft",
        "begin_draft_llm_call",
        "public_draft_job",
        "record_draft_llm_usage",
        "rollback_cancelled_draft",
        "update_draft_job",
    ],
)

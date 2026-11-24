from __future__ import annotations

from server.app_deps import threading, Any, Header, HTTPException, StreamingResponse
from server.registry import deps
from server.modules.job_publication import public_job


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return public_job(job, {"request"})


def _snapshot(job_id: str) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.PROFILE_SUGGESTION_JOBS, deps.PROFILE_SUGGESTION_JOBS_LOCK)
    with deps.PROFILE_SUGGESTION_JOBS_LOCK:
        job = deps.PROFILE_SUGGESTION_JOBS.get(job_id)
        if job is None:
            deps.raise_missing(job_id, "Profile suggestion job not found.")
        return _public(job)


def _publish(job_id: str) -> None:
    deps.PROGRESS_EVENTS.observe(_snapshot(job_id))


def _run(job_id: str, request) -> None:
    def cancelled() -> bool:
        with deps.PROFILE_SUGGESTION_JOBS_LOCK:
            return bool(deps.PROFILE_SUGGESTION_JOBS[job_id].get("cancelRequested"))

    def progress(phase: str, completed: int, total: int) -> None:
        with deps.PROFILE_SUGGESTION_JOBS_LOCK:
            job = deps.PROFILE_SUGGESTION_JOBS[job_id]
            if job.get("cancelRequested"):
                raise deps.GenerationCancelled("キャスト設定の提案をキャンセルしました。")
            job.update({"phase": phase, "completedRelations": completed, "totalRelations": total,
                        "message": "人物設定を考えています…" if phase == "profile" else f"関係 {completed} / {total}"})
        _publish(job_id)
    try:
        result = deps.track_default_llm_usage(
            "キャスト設定提案", lambda: deps.suggest_character_profile_completion(
                request, progress=progress, should_cancel=cancelled,
            ),
        )
        with deps.PROFILE_SUGGESTION_JOBS_LOCK:
            job = deps.PROFILE_SUGGESTION_JOBS[job_id]
            if job.get("cancelRequested"):
                job.update({"status": "cancelled", "phase": "cancelled",
                            "message": "キャスト設定の提案をキャンセルしました。",
                            "result": result, "completedAt": deps.now_ms()})
            else:
                job.update({"status": "completed", "phase": "completed", "message": "キャスト設定の提案が完了しました。",
                            "result": result, "completedAt": deps.now_ms()})
        _publish(job_id)
    except deps.GenerationCancelled:
        with deps.PROFILE_SUGGESTION_JOBS_LOCK:
            deps.PROFILE_SUGGESTION_JOBS[job_id].update({
                "status": "cancelled", "phase": "cancelled",
                "message": "キャスト設定の提案をキャンセルしました。", "completedAt": deps.now_ms(),
            })
        _publish(job_id)
    except Exception as error:
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        with deps.PROFILE_SUGGESTION_JOBS_LOCK:
            job = deps.PROFILE_SUGGESTION_JOBS[job_id]
            job.update({"status": "failed", "phase": "failed", "message": "キャスト設定を提案できませんでした。",
                        "error": str(detail), "completedAt": deps.now_ms()})
        _publish(job_id)


@deps.app.post("/api/characters/profile-suggestion/jobs")
def start_profile_suggestion_job(request: deps.CharacterProfileSuggestionApiRequest) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.PROFILE_SUGGESTION_JOBS, deps.PROFILE_SUGGESTION_JOBS_LOCK)
    validated = deps.CharacterProfileSuggestionRequest.model_validate(request.model_dump())
    job_id = deps.new_id("profile_suggestion_job")
    initial_phase = "relations" if validated.scope == "relations" else "profile"
    initial_message = "人間関係を生成中" if initial_phase == "relations" else "人物設定を生成中"
    job = {"id": job_id, "status": "generating", "phase": initial_phase, "message": initial_message,
           "cancelRequested": False,
           "completedRelations": 0, "totalRelations": deps.profile_suggestion_target_count(validated), "startedAt": deps.now_ms()}
    with deps.PROFILE_SUGGESTION_JOBS_LOCK:
        deps.PROFILE_SUGGESTION_JOBS[job_id] = job
        initial = _public(job)
    deps.PROGRESS_EVENTS.observe(initial)
    threading.Thread(target=_run, args=(job_id, validated), daemon=True).start()
    return initial


@deps.app.get("/api/characters/profile-suggestion/jobs/{job_id}")
def get_profile_suggestion_job(job_id: str) -> dict[str, Any]:
    return _snapshot(job_id)


@deps.app.post("/api/characters/profile-suggestion/jobs/{job_id}/cancel")
def cancel_profile_suggestion_job(job_id: str) -> dict[str, Any]:
    with deps.PROFILE_SUGGESTION_JOBS_LOCK:
        job = deps.PROFILE_SUGGESTION_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Profile suggestion job not found.")
        if job.get("status") != "generating":
            raise HTTPException(status_code=409, detail="Profile suggestion job is no longer running.")
        job.update({"cancelRequested": True, "status": "cancelled", "phase": "cancelled",
                    "message": "キャスト設定の提案をキャンセルしました。", "completedAt": deps.now_ms()})
        public = _public(job)
    deps.PROGRESS_EVENTS.observe(public)
    return public


@deps.app.get("/api/characters/profile-suggestion/jobs/{job_id}/events")
def stream_profile_suggestion_job(job_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    _snapshot(job_id)
    sequence = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(deps.stream_progress(_snapshot, job_id, sequence), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


deps.register(__name__, ["cancel_profile_suggestion_job", "get_profile_suggestion_job", "start_profile_suggestion_job"])

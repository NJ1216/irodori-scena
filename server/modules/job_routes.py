from __future__ import annotations

from server.app_deps import threading, Any, Header, HTTPException, StreamingResponse
from server.registry import deps


def _new_direction_job(job_id: str, request: deps.AiDirectionRequest) -> dict[str, Any]:
    return {
        "id": job_id, "mode": "direction", "status": "planning", "phase": "starting", "cancelRequested": False,
        "message": "AI演出を開始しています…", "totalLines": len(request.line_ids),
        "performanceTotalLines": len(request.line_ids), "performanceCompletedLines": 0,
        "receivedCharacters": 0, "receivedRecords": 0, "performanceAttempt": 0,
        "renderLineIds": [], "startedAt": deps.now_ms(), "llmCallCount": 0,
    }


def _new_draft_job(job_id: str, request: deps.DraftRequest, project: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job_id, "mode": "draft", "status": "planning", "cancelRequested": False,
        "message": "台本生成を開始しています…", "title": "", "totalChunks": 0,
        "currentChunk": 0, "completedChunks": 0, "appendedLines": 0, "appendedCueCount": 0, "estimatedSeconds": 0,
        "phase": "starting", "llmCallCount": 0, "dialogueAttempt": 0,
        "currentChunkAcceptedCharacters": 0, "currentChunkTargetCharacters": 0,
        "requestedCharacters": 0, "receivedCharacters": 0, "receivedRecords": 0,
        "acceptedCharactersTotal": 0,
        "targetCharacters": max(160, round(request.target_minutes * 360 * request.speech_rate)),
        "generatedCharacters": 0,
        "progressUpdatedAt": deps.now_ms(), "overallProgress": 0.0, "adaptiveYieldRatio": 1.0,
        "yieldSamples": 0, "lastYieldRatio": None, "loopDetected": "", "performanceAttempt": 0,
        "performanceCompletedLines": 0, "performanceTotalLines": 0, "transitionCompleted": 0,
        "notationCompletedSteps": 0, "notationTotalSteps": 3,
        "transitionTotal": 0, "performanceTextCorrections": 0, "contextFallbackReason": "", "usedTokens": 0,
        "tokenUsageAvailable": True,
        "targetReached": True, "lengthAccepted": True, "shortfallCharacters": 0,
        "minimumAcceptableCharacters": deps.minimum_acceptable_characters(
            max(160, round(request.target_minutes * 360 * request.speech_rate))
        ),
        "actualCharacters": 0, "plannedBlocks": 0, "completedBlocks": 0, "supplementUsed": False,
        "plannedChapters": 0, "completedChapters": 0,
        "plannedDevelopments": 0, "completedDevelopments": 0,
        "plannedPrimaryCalls": 0, "plannedReserveCalls": 0,
        "usedPrimaryCalls": 0, "usedReserveCalls": 0, "processedDevelopments": 0,
        "predictedCalls": 0, "hardCallCap": 0,
        "plannedCoverageCalls": 0, "plannedRecoveryCalls": 0, "plannedEndingCalls": 0,
        "usedCoverageCalls": 0, "usedRecoveryCalls": 0, "usedEndingCalls": 0,
        "endingAttempted": False, "endingCompleted": False, "storyCompleted": False,
        "completionReason": "",
        "failedDialogueCalls": 0, "detailPlanningCalls": 0,
        "planningFallbackUsed": False, "planningFallbackReason": "", "inputSectionCount": 0,
        "authorEndingSourceId": "", "authorEndingText": "", "authorEndingCompleted": False,
        "partialReason": "",
        "startedAt": deps.now_ms(), "chunks": [], "appendedSceneIds": [],
        "previousTitle": str(project.get("title", "")),
        "_projectId": project.get("id"), "_projectRoot": str(deps.ACTIVE_PROJECT_ROOT),
    }


@deps.app.post("/api/ai/jobs")
def start_ai_job(request: deps.AiJobApiRequest) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.DRAFT_JOBS, deps.DRAFT_JOBS_LOCK)
    request = deps.AiJobRequest.model_validate(request.model_dump())
    if deps.active_draft_job() or deps.active_export_job():
        raise HTTPException(status_code=409, detail="別のAI処理またはエクスポートが進行中です。")
    if request.mode == "draft":
        draft = deps.resolve_logical_llm_request(request.draft_request())
        job_id = deps.new_id("ai_job")
        with deps.PROJECT_ROOT_LOCK:
            project = deps.read_project()
            characters = [deps.find_character(project, item) for item in draft.character_ids]
            job = _new_draft_job(job_id, draft, project)
        job.update(provider=draft.provider, model=draft.model, operationId=job_id)
        deps.begin_llm_operation(job_id, "AI台本生成", draft.provider, draft.model)
        worker = threading.Thread(target=deps.run_draft_job, args=(job_id, draft, characters), daemon=True)
    else:
        direction = deps.resolve_logical_llm_request(request.direction_request())
        job_id = deps.new_id("ai_job")
        job = _new_direction_job(job_id, direction)
        job.update(provider=direction.provider, model=direction.model, operationId=job_id)
        deps.begin_llm_operation(job_id, "AI演出", direction.provider, direction.model)
        worker = threading.Thread(target=deps.run_ai_direction, args=(job_id, direction), daemon=True)
    with deps.DRAFT_JOBS_LOCK:
        deps.DRAFT_JOBS[job_id] = job
        initial = deps.public_draft_job(job)
    deps.PROGRESS_EVENTS.observe(initial)
    worker.start()
    return initial


@deps.app.get("/api/ai/jobs/{job_id}")
def get_ai_job(job_id: str) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.DRAFT_JOBS, deps.DRAFT_JOBS_LOCK)
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is None or not str(job_id).startswith("ai_job_"):
            deps.raise_missing(job_id, "AI job not found.")
        return deps.public_draft_job(job)


@deps.app.get("/api/ai/jobs/{job_id}/events")
def stream_ai_job(job_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    # Resolve once before creating a streaming response so unknown IDs remain a
    # normal JSON 404 instead of failing after response headers were sent.
    get_ai_job(job_id)
    sequence = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(
        deps.stream_progress(get_ai_job, job_id, sequence), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@deps.app.post("/api/ai/jobs/{job_id}/cancel")
def cancel_ai_job(job_id: str) -> dict[str, Any]:
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is None or not str(job_id).startswith("ai_job_"):
            raise HTTPException(status_code=404, detail="AI job not found.")
        if job.get("status") not in {"planning", "generating"} or job.get("_saveCommitted"):
            raise HTTPException(status_code=409, detail="This AI direction job is no longer running.")
        job["cancelRequested"] = True
    deps.close_draft_llm_response(job_id)
    if job.get("mode") == "draft":
        deps.rollback_cancelled_draft(job_id)
        message = "生成をキャンセルしました。台本は変更していません。"
    else:
        message = "AI演出をキャンセルしました。台本は変更していません。"
    deps.update_draft_job(job_id, status="cancelled", phase="cancelled", message=message, completedAt=deps.now_ms())
    with deps.DRAFT_JOBS_LOCK:
        return deps.public_draft_job(deps.DRAFT_JOBS[job_id])


def start_draft_job(request: deps.DraftRequest) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.DRAFT_JOBS, deps.DRAFT_JOBS_LOCK)
    if deps.active_draft_job():
        raise HTTPException(status_code=409, detail="別のAI台本生成が進行中です。完了を待ってください。")
    job_id = deps.new_id("draft_job")
    with deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        characters = [deps.find_character(project, item) for item in request.character_ids]
        job = _new_draft_job(job_id, request, project)
    with deps.DRAFT_JOBS_LOCK:
        deps.DRAFT_JOBS[job_id] = job
        initial = deps.public_draft_job(job)
    deps.PROGRESS_EVENTS.observe(initial)
    worker = threading.Thread(target=deps.run_draft_job, args=(job_id, request, characters), daemon=True)
    worker.start()
    return initial


def get_draft_job(job_id: str) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.DRAFT_JOBS, deps.DRAFT_JOBS_LOCK)
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is None:
            deps.raise_missing(job_id, "Draft job not found. Restart the draft if the server was restarted.")
        return deps.public_draft_job(job)


def cancel_draft_job(job_id: str) -> dict[str, Any]:
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404, detail="Draft job not found. Restart the draft if the server was restarted."
            )
        if job.get("status") not in {"planning", "generating"} or job.get("_saveCommitted"):
            raise HTTPException(status_code=409, detail="This draft job is no longer running.")
        job["cancelRequested"] = True
    deps.close_draft_llm_response(job_id)
    deps.rollback_cancelled_draft(job_id)
    deps.update_draft_job(
        job_id,
        status="cancelled",
        phase="cancelled",
        message="生成をキャンセルしました。台本は変更していません。",
        completedAt=deps.now_ms(),
    )
    with deps.DRAFT_JOBS_LOCK:
        return deps.public_draft_job(deps.DRAFT_JOBS[job_id])


@deps.app.post("/api/exports/jobs")
def start_export_job(request: deps.ExportStartRequest) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.EXPORT_JOBS, deps.EXPORT_JOBS_LOCK)
    if deps.active_draft_job():
        raise HTTPException(status_code=409, detail="AI台本を生成中です。完了後にエクスポートできます。")
    if deps.active_export_job():
        raise HTTPException(status_code=409, detail="まとめてエクスポートが進行中です。")
    if request.mode == "bundle" and "lab" in request.formats and not deps.rhubarb_status()["ready"]:
        raise HTTPException(status_code=409, detail="口パクLABをエクスポートするにはRhubarbを追加してください。")
    project = deps.read_project()
    export_lines = deps.export_spoken_lines(project)
    total_lines = len(export_lines)
    if not total_lines:
        raise HTTPException(status_code=422, detail="エクスポートする本文のある発話行がありません。")
    job_id = deps.new_id("export_job")
    request_data = request.model_dump(by_alias=True)
    needs_audio = request.mode == "prepare" or any(item in {"wav", "srt"} for item in request.formats)
    job = {
        "id": job_id,
        "status": "preparing",
        "phase": "preparing",
        "message": "エクスポートを準備しています…" if request.mode == "bundle" else "未生成の発話行を確認しています…",
        "joinOutput": False,
        "mode": request.mode,
        "request": request_data,
        "totalLines": total_lines,
        "currentLine": 0,
        "currentLineId": None,
        "completedLines": 0,
        "generatedLines": 0,
        "alignmentCompletedLines": 0,
        "alignmentTotalLines": 0,
        "requiresGeneration": needs_audio and any(not deps.selected_take_is_available(line) for _, line in export_lines),
        "destinationPath": None,
        "artifactCount": 0,
        "updateVersion": 0,
        "lineUpdates": [],
        "cancelRequested": False,
        "startedAt": deps.now_ms(),
    }
    with deps.EXPORT_JOBS_LOCK:
        deps.EXPORT_JOBS[job_id] = job
        initial = deps.public_export_job(job)
    deps.PROGRESS_EVENTS.observe(initial)
    threading.Thread(target=deps.run_export_job, args=(job_id,), daemon=True).start()
    return initial


@deps.app.get("/api/exports/jobs/{job_id}")
def get_export_job(job_id: str, after_update: int = 0) -> dict[str, Any]:
    deps.evict_terminal_jobs(deps.EXPORT_JOBS, deps.EXPORT_JOBS_LOCK)
    with deps.EXPORT_JOBS_LOCK:
        job = deps.EXPORT_JOBS.get(job_id)
        if job is None:
            deps.raise_missing(job_id, "Export job not found. Restart the export if the server was restarted.")
        return deps.public_export_job(job, after_update=max(0, after_update))


@deps.app.get("/api/exports/jobs/{job_id}/events")
def stream_export_job(job_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    get_export_job(job_id)
    sequence = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(
        deps.stream_progress(get_export_job, job_id, sequence), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@deps.app.post("/api/exports/jobs/{job_id}/cancel")
def cancel_export_job(job_id: str) -> dict[str, Any]:
    with deps.EXPORT_JOBS_LOCK:
        job = deps.EXPORT_JOBS.get(job_id)
        if job is None:
            raise HTTPException(
                status_code=404, detail="Export job not found. Restart the export if the server was restarted."
            )
        if job.get("status") not in {"preparing", "generating", "aligning", "writing"}:
            raise HTTPException(status_code=409, detail="This export job is no longer running.")
        job["cancelRequested"] = True
        job["message"] = "キャンセルを受け付けました。現在の発話行を完了後に停止します…"
        public = deps.public_export_job(job)
    deps.PROGRESS_EVENTS.observe(public)
    return public


@deps.app.post("/api/exports/jobs/cancel-active")
def cancel_active_export_job() -> dict[str, Any]:
    with deps.EXPORT_JOBS_LOCK:
        job = next(
            (item for item in deps.EXPORT_JOBS.values() if item.get("status") in {"preparing", "generating", "aligning", "writing"}),
            None,
        )
        if job is None:
            raise HTTPException(status_code=409, detail="停止できるエクスポートはありません。")
        job["cancelRequested"] = True
        job["message"] = "キャンセルを受け付けました。現在の発話行を完了後に停止します…"
        public = deps.public_export_job(job)
    deps.PROGRESS_EVENTS.observe(public)
    return public


deps.register(
    __name__,
    ["cancel_active_export_job", "cancel_ai_job", "cancel_draft_job", "cancel_export_job", "get_ai_job", "get_draft_job", "get_export_job", "start_ai_job", "start_draft_job", "start_export_job", "stream_ai_job", "stream_export_job"],
)

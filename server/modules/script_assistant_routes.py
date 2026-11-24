from __future__ import annotations

from server.app_deps import Header, HTTPException, StreamingResponse, threading
from server.registry import deps


@deps.app.post("/api/lines/assistant/suggest-v2")
def suggest_script_assistant_instruction(request: deps.ScriptAssistantApiRequest) -> dict[str, str]:
    internal = deps.ScriptAssistantRequest.model_validate(request.model_dump())
    random_idea = not internal.instruction.strip()
    project = deps.read_project()
    groups = deps.prepare_script_assistant_groups(project, internal)
    context = deps.script_assistant_context(project, groups[0])
    recent = [deps.dialogue_row(item) for item in context["recentRows"]]
    selected = [deps.dialogue_row(item) for item in context["selectedRows"]]
    following = [deps.dialogue_row(item) for item in context["followingRows"]]
    characters = [
        {"name": item.get("name", ""), "profile": item.get("profile", "")}
        for item in project.get("characters", []) if str(item.get("id", "")) in internal.character_ids
    ]
    system = (
        "あなたは日本語音声台本の企画担当です。前後の台本と参加キャストから、自然につながる具体的な挿入内容を一案だけ提案する。台詞本文は書かない。"
        if random_idea
        else "あなたは日本語音声台本の要件整理担当です。作者の要望を、直後の台本編集AIへ渡せる具体的な依頼文に整える。固有名詞、順序、否定条件を保ち、作者が明示していない音響効果を追加しない。台詞本文は書かない。"
    )
    try:
        result = deps.track_default_llm_usage("台本編集要望の整理", lambda: deps.complete_records(
            internal, contract=deps.instruction_contract(), system=system, user={
                "operation": internal.operation, "author_request": internal.instruction or "前後の文脈から提案する",
                "selected_casts": characters, "recent_context": recent,
                "target_rows": selected, "following_three_rows": following,
            }, max_tokens=900, temperature=0.35,
        ))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    instruction = next((row.get("value") for row in result.records if row.get("value")), None)
    if not instruction:
        raise HTTPException(status_code=502, detail="LLMから利用できる要望文を取得できませんでした。")
    return {"instruction": instruction}


@deps.app.post("/api/lines/assistant/jobs")
def start_script_assistant_job(request: deps.ScriptAssistantApiRequest) -> dict:
    deps.evict_terminal_jobs(deps.SCRIPT_ASSISTANT_JOBS, deps.SCRIPT_ASSISTANT_JOBS_LOCK)
    deps.evict_script_assistant_proposals()
    internal = deps.ScriptAssistantRequest.model_validate(request.model_dump())
    if deps.active_draft_job() or deps.active_export_job() or deps.active_script_assistant_job():
        raise HTTPException(status_code=409, detail="別のAI処理またはエクスポートが進行中です。")
    project = deps.read_project()
    deps.prepare_script_assistant_groups(project, internal)
    job_id = deps.new_id("script_assistant_job")
    job = {
        "id": job_id, "status": "planning", "phase": "starting", "message": "AI台本編集を開始しています…",
        "overallProgress": 0.0, "cancelRequested": False, "startedAt": deps.now_ms(),
        "operation": internal.operation, "request": internal.model_dump(), "sourceProject": project,
    }
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        deps.SCRIPT_ASSISTANT_JOBS[job_id] = job
        initial = deps.public_script_assistant_job(job)
    deps.PROGRESS_EVENTS.observe(initial)
    threading.Thread(target=deps.run_script_assistant_job, args=(job_id, internal, project), daemon=True).start()
    return initial


@deps.app.get("/api/lines/assistant/jobs/{job_id}")
def get_script_assistant_job(job_id: str) -> dict:
    deps.evict_terminal_jobs(deps.SCRIPT_ASSISTANT_JOBS, deps.SCRIPT_ASSISTANT_JOBS_LOCK)
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        job = deps.SCRIPT_ASSISTANT_JOBS.get(job_id)
        if job is None:
            deps.raise_missing(job_id, "AI台本編集ジョブが見つかりません。")
        return deps.public_script_assistant_job(job)


@deps.app.get("/api/lines/assistant/jobs/{job_id}/events")
def stream_script_assistant_job(job_id: str, last_event_id: str | None = Header(default=None, alias="Last-Event-ID")):
    get_script_assistant_job(job_id)
    sequence = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    return StreamingResponse(
        deps.stream_progress(get_script_assistant_job, job_id, sequence), media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@deps.app.post("/api/lines/assistant/jobs/{job_id}/cancel")
def cancel_script_assistant_job(job_id: str) -> dict:
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        job = deps.SCRIPT_ASSISTANT_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="AI台本編集ジョブが見つかりません。")
        if job.get("status") not in {"planning", "generating"}:
            raise HTTPException(status_code=409, detail="このAI台本編集は実行中ではありません。")
        job["cancelRequested"] = True
    deps.close_draft_llm_response(job_id)
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        public = deps.public_script_assistant_job(deps.SCRIPT_ASSISTANT_JOBS[job_id])
    deps.PROGRESS_EVENTS.observe(public)
    return public


@deps.app.post("/api/lines/assistant/proposals/{proposal_id}/apply")
def apply_script_assistant(proposal_id: str, request: deps.ScriptAssistantApplyRequest) -> dict:
    deps.evict_script_assistant_proposals()
    if proposal_id not in deps.SCRIPT_ASSISTANT_PROPOSALS:
        deps.raise_missing(proposal_id, "AI台本編集の提案が見つかりません。")
    if proposal_id != request.proposal_id:
        raise HTTPException(status_code=422, detail="提案IDが一致しません。")
    if deps.active_draft_job() or deps.active_export_job() or deps.active_script_assistant_job():
        raise HTTPException(status_code=409, detail="別の処理が完了してから提案を適用してください。")
    return deps.apply_script_assistant_proposal(request)


deps.register(__name__, [
    "apply_script_assistant", "cancel_script_assistant_job", "get_script_assistant_job",
    "start_script_assistant_job", "stream_script_assistant_job", "suggest_script_assistant_instruction",
])

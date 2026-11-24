from __future__ import annotations

from server.app_deps import json, Any
from server.registry import deps
from server.modules import draft_packet_budget, draft_schedule
from server.modules.llm_retry_budget import DraftRetryBudget
from server.modules.draft_dialogue_job import DraftDialogueRun
from server.modules.ollama_context import DraftContextError


def _fail(job_id: str, code: str, message: str, error: str = "") -> None:
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id, {})
        target = int(job.get("targetCharacters", 0))
        actual = int(job.get("actualCharacters", job.get("acceptedCharactersTotal", 0)))
    deps.update_draft_job(job_id, status="failed", phase="failed", failureCode=code, message=message,
                          error=error, lengthAccepted=False, targetReached=False,
                          shortfallCharacters=max(0, target - actual), completedAt=deps.now_ms())


def _optional_fields(characters: list[dict[str, Any]]) -> dict[str, set[str]]:
    fields = set(deps.DRAFT_OPTIONAL_PROFILE_FIELDS)
    return {str(character.get("id", "")): set(fields) for character in characters}


def _normalize(raw, *, permitted, name_to_id, chapter_index, prior_texts, limit):
    candidate = deps.normalize_draft_dialogue(raw, permitted=permitted,
        character_name_to_id=name_to_id, chapter_index=chapter_index, line_offset=0)
    clean, discarded = [], 0
    for line in candidate.get("lines", []):
        if deps.has_excessive_draft_repetition([{"lines": [line]}]):
            discarded += 1
        else:
            clean.append(line)
    candidate["lines"] = clean
    candidate, blocks = deps.remove_repeated_draft_blocks(candidate, [])
    candidate, texts = deps.remove_repeated_draft_dialogue(candidate, prior_texts)
    return candidate, discarded + blocks + texts


def _prepare_developments(
    job_id, request, chapters, total, cast_context, token_budget, debug_directory, source_capacity=None,
):
    del job_id, request, cast_context, token_budget, debug_directory
    beats = deps.planned_draft_beats(chapters, total, source_capacity=source_capacity, short_framing=True)
    grouped = [[] for _ in chapters]
    for beat in beats:
        grouped[beat.chapter_index].append(f"{beat.source}|{beat.text}")
    return grouped, {beat.source: beat.target_characters for beat in beats}, 0


def _store_candidate(drafted, candidate, source_chapters, fallback_chapter, discarded):
    for index in range(len(drafted)):
        owned = [line for line in candidate["lines"]
                 if source_chapters.get(str(line.get("development_id", "")), fallback_chapter) == index]
        drafted[index]["dialogue"]["lines"].extend(owned)
        deps.resequence_draft_dialogue(drafted[index]["dialogue"], index)
        drafted[index]["spoken"] += deps.spoken_dialogue_count({"lines": owned})
    drafted[fallback_chapter]["discarded_duplicates"] += discarded


def _packet_context(chapters, selected, source_chapters, final_packet, cast_context, characters, aliases):
    grouped = {index: [item for item in selected
                       if source_chapters.get(item.split("|", 1)[0]) == index]
               for index in range(len(chapters))}
    packet = [{**chapters[index], "beats": beats, "mandatory_completion": True,
               "final_conclusion": index == len(chapters) - 1}
              for index, beats in grouped.items() if beats]
    if final_packet:
        return packet, cast_context, aliases
    context = deps.draft_chapter_cast_context(cast_context, packet[0], characters)
    speakers = {str(item.get("cast", "")) for item in context if item.get("chapter_role") == "speaker"}
    return packet[0], context, {cast_id: alias for cast_id, alias in aliases.items() if alias in speakers}


def draft_schema_batching_available(request) -> bool:
    if deps.ollama_structured_enabled(request):
        return True
    capabilities = deps.resolve_llm_capabilities(request.provider, request.base_url, request.model)
    structured = capabilities.get("structuredOutput") if isinstance(capabilities, dict) else None
    streaming = structured.get("streaming") if isinstance(structured, dict) else None
    return (
        isinstance(streaming, dict)
        and streaming.get("state") in {"constrained", "schema_validated"}
    )


def _batch_shrink_reasons(raw: dict[str, Any], failure: str, missing: list[str], discarded: int,
                          reordered: bool) -> list[str]:
    reasons = []
    manifest = raw.get("_manifest", [])
    rejected = [item for item in manifest if isinstance(item, dict) and item.get("status") == "rejected"]
    if failure:
        reasons.append("stream_interrupted" if "stream interrupted" in failure else "generation_failure")
    if raw.get("_partial"):
        reasons.append("truncated_response")
    if missing:
        reasons.append("missing_development")
    if any(item.get("reason") == "unknown_owner" for item in rejected):
        reasons.append("unknown_source")
    if any(item.get("reason") == "conflicting_field" for item in rejected):
        reasons.append("conflicting_record")
    if discarded:
        reasons.append("repetition")
    if reordered:
        reasons.append("source_reordered")
    return list(dict.fromkeys(reasons))


def run_forward_draft_job(job_id: str, request: deps.DraftRequest, characters: list[dict[str, Any]]) -> None:
    deps.DRAFT_LLM_THREAD_CONTEXT.job_id = job_id
    deps.DRAFT_LLM_THREAD_CONTEXT.retry_budget = DraftRetryBudget()
    usage_card_id = deps.default_llm_card_id()
    try:
        _run(job_id, request, characters, usage_card_id)
    except deps.GenerationCancelled:
        deps._cancel_draft_job(job_id)
        deps.record_llm_usage(usage_card_id, "AI台本生成", False, "cancelled")
    except Exception as error:
        code = error.code if isinstance(error, DraftContextError) else (
            "draft_transport_failed" if isinstance(error, deps.TransportFailure) else "draft_no_usable_output")
        _fail(job_id, code, "台本生成を完了できませんでした。台本は追加していません。", str(error))
        deps.record_llm_usage(usage_card_id, "AI台本生成", False, type(error).__name__)
    finally:
        with deps.DRAFT_JOBS_LOCK:
            job = deps.DRAFT_JOBS.get(job_id, {})
            terminal = {key: job.get(key) for key in ("status", "failureCode", "partialReason", "error", "appendedLines")}
        deps.write_draft_debug_response(deps.draft_debug_directory(job_id) / "job-result.json",
                                        json.dumps(terminal, ensure_ascii=False, indent=2))
        deps.DRAFT_LLM_THREAD_CONTEXT.job_id = None
        deps.DRAFT_LLM_THREAD_CONTEXT.retry_budget = None
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None
        with deps.DRAFT_LLM_RESPONSES_LOCK:
            deps.DRAFT_LLM_RESPONSES.pop(job_id, None)


def _run(job_id: str, request: deps.DraftRequest, characters: list[dict[str, Any]], usage_card_id: str) -> None:
    debug_directory = deps.draft_debug_directory(job_id)
    with deps.PROJECT_ROOT_LOCK, deps.DRAFT_JOBS_LOCK:
        deps.DRAFT_JOBS[job_id].setdefault("_projectRoot", str(deps.ACTIVE_PROJECT_ROOT))
        deps.DRAFT_JOBS[job_id].setdefault("_projectId", deps.read_project().get("id"))
    deps.update_draft_job(
        job_id,
        status="planning",
        phase="context",
        message="キャラクターの設定をまとめています…",
        phaseStartedAt=deps.now_ms(),
        targetMinutes=request.target_minutes,
    )
    target = draft_packet_budget.duration_character_target(request)
    generation_target = target
    with deps.DRAFT_JOBS_LOCK:
        configured_seed = deps.DRAFT_JOBS.get(job_id, {}).get("benchmarkSeed")
    benchmark_seed = int(configured_seed) if isinstance(configured_seed, int) else None
    minimum = deps.minimum_acceptable_characters(target)
    with deps.DRAFT_JOBS_LOCK:
        benchmark_schema = deps.DRAFT_JOBS.get(job_id, {}).get("benchmarkRequiredSourceSchema") is True
    aliases = deps.draft_cast_aliases(characters)
    cast_context = deps.draft_cast_context(characters, cast_alias_by_id=aliases,
        request=request, optional_fields_by_cast=_optional_fields(characters))
    capability = deps.build_draft_capability_profile(
        request, cast_context, adaptive_long_form=True, should_cancel=lambda: deps.draft_cancel_requested(job_id),
    )
    deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = capability
    token_budget, max_block = int(capability["outputTokenLimit"]), int(capability["maxChunkCharacters"])
    dynamic_long_form = capability.get("adaptiveLongForm") is True
    schema_batching = deps.draft_schema_batching_available(request) or benchmark_schema
    adaptive_batch_size = 1
    maximum_batch_size = 3 if schema_batching else 1
    initial_yield, yield_samples = deps.draft_yield_ratio(request)
    performance_profile = deps.draft_performance_profile(request)
    cast_context_audit = [{"cast": aliases[str(item["id"])], "cache": "deterministic"} for item in characters]
    text_cast = deps.draft_text_cast_context(cast_context)
    deps.advance_draft_progress(job_id, overall_progress=deps.DRAFT_PROGRESS_CONTEXT)
    deps.update_draft_job(job_id, status="planning", phase="planning", message="全体構成を設計しています…",
        phaseStartedAt=deps.now_ms(),
        targetCharacters=target, minimumAcceptableCharacters=minimum,
        adaptiveYieldRatio=round(initial_yield, 4), yieldSamples=yield_samples,
        castContext=cast_context, castContextAudit=cast_context_audit)
    plan = deps.create_draft_plan(request, cast_context=text_cast, chunk_count=1,
        target_characters=generation_target, token_budget=token_budget, debug_directory=debug_directory,
        on_call=lambda _: deps.begin_draft_llm_call(job_id, phase="planning", message="全体構成を設計しています…"),
        should_cancel=lambda: deps.draft_cancel_requested(job_id), job_id=job_id,
        benchmark_seed=benchmark_seed)
    deps.advance_draft_progress(job_id, overall_progress=deps.DRAFT_PROGRESS_PLANNING)
    chapters = plan["chapters"]
    source_capacity = (performance_profile["acceptedCharacters"] if dynamic_long_form
                       else draft_schedule.development_capacity(max_block))
    developments, planned_source_targets, detail_calls = _prepare_developments(
        job_id, request, chapters, generation_target, text_cast, token_budget, debug_directory,
        source_capacity=source_capacity)
    development_count = sum(len(items) for items in developments)
    schedule = draft_schedule.planned_call_budget(
        development_count, structured=schema_batching, learned_batch=performance_profile["batch"])
    predicted_calls = schedule["predicted"]
    deps.update_draft_job(job_id, title=str(plan.get("title", "")).strip() or "生成台本",
        status="generating", phase="dialogue", plannedChapters=len(chapters), completedChapters=0,
        plannedDevelopments=development_count, completedDevelopments=0, failedDialogueCalls=0,
        detailPlanningCalls=detail_calls, planningFallbackUsed=bool(plan.get("_planning_fallback_used")),
        planningFallbackReason=str(plan.get("_planning_fallback_reason", "")),
        inputSectionCount=len(plan.get("_source_sections", [])),
        authorEndingSourceId=str((plan.get("_author_ending") or {}).get("id", "")),
        authorEndingText=str((plan.get("_author_ending") or {}).get("text", "")),
        authorEndingCompleted=False,
        partialReason="", plannedBlocks=development_count, completedBlocks=0, totalChunks=schedule["hardCap"],
        predictedCalls=predicted_calls, hardCallCap=schedule["hardCap"],
        plannedCoverageCalls=schedule["coverage"], plannedRecoveryCalls=schedule["recovery"],
        plannedEndingCalls=schedule["ending"], usedCoverageCalls=0, usedRecoveryCalls=0, usedEndingCalls=0,
        endingAttempted=False, endingCompleted=False, storyCompleted=False,
        plannedDialogueCalls=schedule["hardCap"],
        plannedPrimaryCalls=schedule["primary"], plannedReserveCalls=schedule["reserve"],
        usedPrimaryCalls=0, usedReserveCalls=0, processedDevelopments=0)
    deps.update_draft_job(job_id, selectedContext=capability.get("effectiveContext"),
        adaptiveLongForm=dynamic_long_form, predictedDialogueCalls=predicted_calls,
        plannedOutputTokenLimit=token_budget, plannedMaxChunkCharacters=max_block,
        initialDialogueBatchSize=adaptive_batch_size, maximumDialogueBatchSize=maximum_batch_size,
        usedDialogueBatchSizes=[], retryInputTokens=0, developmentAcceptance={},
        dialogueBatchShrinkReasons=[], dialogueBatchHistory=[])
    execution = DraftDialogueRun(job_id, request, characters, plan, developments, planned_source_targets,
                                 capability, cast_context, aliases, debug_directory, benchmark_seed)
    drafted, partial_reason = execution.execute()
    accepted, partial_continuation_used = execution.accepted, execution.partial_continuation
    names_by_id = execution.names_by_id
    usable = [item for item in drafted if item["dialogue"].get("lines")]
    if not usable:
        _fail(job_id, execution.stop_reason or "draft_no_usable_output",
              "利用できる台詞を生成できませんでした。台本は追加していません。")
        deps.record_llm_usage(usage_card_id, "AI台本生成", False, "no usable output")
        return
    usable = deps.normalize_draft_notation_locally(usable)
    deps.update_draft_job(job_id, phase="performance", message="検証・保存しています…")
    try:
        deps._direct_draft_chapters(job_id, request, usable, chapters,
            deps.draft_performance_cast_context(cast_context), aliases, names_by_id, token_budget,
            debug_directory, str(plan.get("title", "")).strip() or "生成台本",
            deps._script_cast_contexts(plan, cast_context, aliases))
    except deps.GenerationCancelled:
        raise
    except Exception as error:
        _fail(job_id, getattr(error, "code", "draft_save_failed"),
              "生成済み台本を保存できませんでした。台本は追加していません。", str(error))
        deps.record_llm_usage(usage_card_id, "AI台本生成", False, "save failed")
        return
    seconds = float(deps.DRAFT_JOBS.get(job_id, {}).get("estimatedSeconds", 0))
    duration_ok = request.target_minutes * 50 <= seconds <= request.target_minutes * 70
    if not duration_ok:
        partial_reason = ",".join(filter(None, (partial_reason, "duration_out_of_range")))
    ending_completed = bool(execution.ending_source in execution.completed)
    story_completed = ending_completed and not execution.finalized_incomplete
    completion_reason = ("story_completed" if story_completed and duration_ok else
                         "story_completed_short" if story_completed else
                         "ending_incomplete" if execution.attempt_counts.get(execution.ending_source, 0) else
                         "ending_not_attempted")
    deps.update_draft_job(job_id, status="completed", phase="completed", actualCharacters=accepted,
        lengthAccepted=duration_ok, targetReached=accepted >= target,
        shortfallCharacters=max(0, target - accepted), overallProgress=100.0,
        message=("台本を追加しました。" if not partial_reason else
                 "一部の生成に不足がありますが、生成済み台本を追加しました"),
        completedAt=deps.now_ms(), partialReason=partial_reason,
        generatedSceneCount=len({str(line.get("development_id", ""))
                                 for item in drafted for line in item["dialogue"].get("lines", [])
                                 if str(line.get("development_id", ""))}),
        partialContinuationUsed=partial_continuation_used,
        endingAttempted=execution.attempt_counts.get(execution.ending_source, 0) > 0,
        endingCompleted=ending_completed, storyCompleted=story_completed,
        completionReason=completion_reason)
    deps.record_llm_usage(usage_card_id, "AI台本生成", True)
    try:
        deps.start_tts_prepare(after_draft=True)
    except Exception:
        # Draft persistence is complete; speculative TTS preparation is best-effort.
        pass


deps.register(__name__, ["draft_schema_batching_available", "run_forward_draft_job"])

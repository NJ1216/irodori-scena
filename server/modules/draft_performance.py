from __future__ import annotations

from server.app_deps import Path, Any, Callable
from server.registry import deps


def _direction_request(request: deps.DraftRequest) -> deps.AiDirectionRequest:
    settings = request.cast_settings
    emoji_enabled = any(
        (settings.get(cast_id).emoji_expressions if settings.get(cast_id) else request.emoji_expressions)
        for cast_id in request.character_ids
    ) and bool(request.allowed_emojis)
    return deps.AiDirectionRequest(
        base_url=request.base_url,
        model=request.model,
        api_key=request.api_key,
        provider=request.provider,
        line_ids=["draft-performance"],
        emoji_expressions=emoji_enabled,
        speech_rate=True,
        gap_seconds=True,
        stage_direction=True,
        overwrite_existing=True,
        allowed_emojis=sorted(deps.ai_allowed_emojis(request, request.allowed_emojis)) if emoji_enabled else [],
        speech_rate_min=request.performance_speech_rate_min,
        speech_rate_max=request.performance_speech_rate_max,
        gap_min=request.performance_gap_min,
        gap_max=request.performance_gap_max,
        allow_negative_gap=request.overlapping_speech,
    )


def _rows(
    lines: list[dict[str, Any]],
    names_by_id: dict[str, str],
    *,
    start: int = 1,
) -> list[dict[str, Any]]:
    return [
        {
            "alias": f"L{index}",
            "id": str(line["line_id"]),
            "character_id": str(line.get("character_id", "")),
            "name": names_by_id.get(str(line.get("character_id", "")), "?"),
            "text": str(line.get("text", "")),
            "rate": "未設定",
            "gap": "未設定",
            "stage": "",
        }
        for index, line in enumerate(lines, start=start)
    ]


def _draft_line(source: dict[str, Any], update: dict[str, Any]) -> dict[str, Any]:
    text = str(update.get("text", source["text"]))
    result = {
        "id": deps.new_id("line"),
        "characterId": source["character_id"],
        "text": text,
        "takes": [],
        "selectedTakeId": None,
    }
    if update.get("stageDirection") not in (None, ""):
        result["stageDirection"] = update["stageDirection"]
    if update.get("speechRate") not in (None, ""):
        result["speechRate"] = update["speechRate"]
    if update.get("gapSeconds") not in (None, ""):
        result["gapSeconds"] = update["gapSeconds"]
    if update.get("simultaneous_candidate_id"):
        result["simultaneous_candidate_id"] = update["simultaneous_candidate_id"]
    return result


def _validate_chunk_cues(source_lines: list[dict[str, Any]], updates: dict[str, dict[str, Any]]) -> None:
    positions: dict[str, list[int]] = {}
    for index, source in enumerate(source_lines):
        marker = str(updates.get(str(source["line_id"]), {}).pop("simultaneous_marker", "")).strip()
        if marker:
            positions.setdefault(marker, []).append(index)
    for indexes in positions.values():
        runs: list[list[int]] = []
        for index in indexes:
            if runs and index == runs[-1][-1] + 1:
                runs[-1].append(index)
            else:
                runs.append([index])
        for run in runs:
            members = [source_lines[index] for index in run]
            valid = (
                2 <= len(members) <= 8
                and len({str(line.get("character_id", "")) for line in members}) == len(members)
                and not any(deps.is_inner_monologue_text(str(line.get("text", ""))) for line in members)
            )
            if valid:
                candidate_id = deps.new_id("draft_cue")
                for index in run:
                    updates[str(source_lines[index]["line_id"])]["simultaneous_candidate_id"] = candidate_id


def direct_draft_performance(
    request: deps.DraftRequest,
    *,
    job_id: str,
    cast_context: list[dict[str, Any]],
    chapter: dict[str, Any],
    dialogue: dict[str, Any],
    lookahead_lines: list[dict[str, Any]],
    cast_alias_by_id: dict[str, str],
    prior_performance_state: str,
    token_budget: int,
    debug_directory: Path,
    chapter_index: int,
    total_chapters: int | None = None,
    completed_lines_before: int = 0,
    performance_total_lines: int | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_text_corrections: Callable[[int], None] | None = None,
    allow_llm_fallback: bool = True,
) -> list[dict[str, Any]]:
    """Direct generated dialogue through the same engine used by AI direction."""
    del prior_performance_state, token_budget, should_cancel, on_text_corrections
    names_by_alias = {str(cast.get("cast", "")): str(cast.get("name", "")) for cast in cast_context}
    names_by_id = {
        cast_id: names_by_alias.get(alias, "?")
        for cast_id, alias in cast_alias_by_id.items()
    }
    source_lines = dialogue.get("lines", [])
    rows = _rows(source_lines, names_by_id)
    lookahead = _rows(lookahead_lines, names_by_id, start=len(rows) + 1)
    direction_request = _direction_request(request)
    emoji_enabled_by_character = {
        cast_id: (request.cast_settings.get(cast_id).emoji_expressions if request.cast_settings.get(cast_id) else request.emoji_expressions)
        for cast_id in request.character_ids
    }
    for row in [*rows, *lookahead]:
        row["emoji_allowed"] = emoji_enabled_by_character.get(str(row.get("character_id", "")), False)
    chunk_size = deps.direction_chunk_size(deps.active_draft_capability_profile())
    integrated = {
        str(line["line_id"]): line
        for line in source_lines
        if isinstance(line.get("integrated_direction"), dict)
    }
    with deps.DRAFT_JOBS_LOCK:
        mode = str(deps.DRAFT_JOBS.get(job_id, {}).get("integratedDirectionMode", ""))
    fallback_all = allow_llm_fallback and (mode == "legacy" or (not mode and not any(integrated.values())))
    attempted = {
        str(line["line_id"])
        for line in source_lines
        if line.get("integrated_direction_attempted") is True
    }
    rows_to_direct = rows if fallback_all else [
        row for row in rows if allow_llm_fallback and row["id"] not in attempted
    ]
    chunks = [rows_to_direct[index:index + chunk_size] for index in range(0, len(rows_to_direct), chunk_size)]
    if chunks:
        deps.update_draft_job(job_id, performanceFallbackStepRequired=True)
    updates: dict[str, dict[str, Any]] = {}
    allowed = set(direction_request.allowed_emojis).intersection(deps.AI_PROPOSABLE_EMOJIS)
    valid_field_count = 0
    emoji_proposals = 0
    cue_candidates = 0
    integrated_values = deps.normalize_negative_gap_ownership(
        [
            (row, dict(integrated.get(str(row["id"]), {}).get("integrated_direction", {})))
            for row in rows
        ],
        default_gap=request.line_gap,
        following_row=lookahead[0] if lookahead else None,
    )
    for row_index, row in enumerate(rows):
        source = integrated.get(str(row["id"]))
        if not source:
            continue
        values = integrated_values[row_index]
        emoji_proposals += str(values.get("emoji", "")).strip() not in {"", "NONE"}
        cue_candidates += bool(deps.CUE_MARKER.fullmatch(str(values.get("cue", "")).strip()))
        actual_next_origin = (
            str(source_lines[row_index + 1].get("integrated_direction_origin", ""))
            if row_index + 1 < len(source_lines) else "END"
        )
        if str(source.get("integrated_direction_next_origin", "")) != actual_next_origin:
            values.pop("gap", None)
            values.pop("cue", None)
        character_id = str(row.get("character_id", ""))
        patch = deps.validated_direction_patch(
            request, row, values, allowed, character_id=character_id
        )
        cue = values.get("cue", "").strip()
        if request.simultaneous_cues and deps.CUE_MARKER.fullmatch(cue):
            patch["simultaneous_marker"] = cue
        # Anchors are valid only against the final corrected spoken text.
        if str(source.get("integrated_direction_source_text", "")) != str(row["text"]):
            patch.pop("text", None)
        updates[str(row["id"])] = patch
        valid_field_count += len(patch)
    job_total = performance_total_lines or len(rows)
    for chunk_index, chunk in enumerate(chunks, 1):
        positions = [rows.index(row) for row in chunk]
        start, end = positions[0], positions[-1] + 1
        before = rows[max(0, start - deps.DIRECTION_CONTEXT_SIZE):start]
        after = (rows[end:end + deps.DIRECTION_CONTEXT_SIZE] + lookahead)[:deps.DIRECTION_CONTEXT_SIZE]
        for update in deps.direct_performance_chunk(
            direction_request,
            job_id=job_id,
            chunk=chunk,
            before=before,
            after=after,
            cast_context=cast_context,
            chunk_index=chunk_index,
            chunk_total=len(chunks),
            debug_directory=debug_directory,
            completed_lines_before=completed_lines_before + len(updates),
            performance_total_lines=job_total,
            simultaneous_cues=request.simultaneous_cues and len(request.character_ids) > 1,
            emoji_enabled_by_character=emoji_enabled_by_character,
        ):
            updates[update["id"]] = update
        _validate_chunk_cues(source_lines[start:end], updates)
        completed = completed_lines_before + len(updates)
        deps.advance_draft_progress(
            job_id,
            overall_progress=deps.draft_performance_overall_progress(completed, job_total),
        )
        deps.update_draft_job(
            job_id,
            performanceCompletedLines=completed,
            performanceTotalLines=job_total,
            message="演技設定を検証しています",
            transitionCompleted=len(updates),
            transitionTotal=len(rows),
        )
    _validate_chunk_cues(source_lines, updates)
    emoji_accepted = sum("text" in update for update in updates.values())
    cue_accepted_rows = sum("simultaneous_marker" in update for update in updates.values())
    directed = [_draft_line(source, updates.get(str(source["line_id"]), {})) for source in source_lines]
    deps.update_draft_job(
        job_id,
        integratedDirectionAcceptedFields=valid_field_count,
        integratedEmojiProposals=emoji_proposals,
        integratedEmojiAccepted=emoji_accepted,
        integratedCueCandidates=cue_candidates,
        integratedCueAcceptedPairs=cue_accepted_rows // 2,
        integratedDirectionFallbackReason=("first response contained no usable direction fields" if fallback_all else ""),
    )
    deps.finalize_draft_simultaneous_cues(directed)
    return [{"id": deps.new_id("scene"), "title": str(chapter.get("title", "Scene")), "lines": directed}]


deps.register(__name__, ["direct_draft_performance"])

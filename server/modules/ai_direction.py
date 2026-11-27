from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from server.modules.direction_context import DIRECTION_CONTEXT_SIZE, direction_chunk_size
from server.modules.direction_fields import emoji_enabled_for_cast
from server.registry import deps
from server.modules.ai_direction_response import (  # noqa: F401
    _parse, _record_values, _direction_contract, _project_direction_records, _response_token_limit,
    _direction_number, _enforce_patch_tutting, _directed_emoji_text, _performance_patch, _request_text,
)

def _spoken(project: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    return [
        (scene, line)
        for scene in project.get("scenes", [])
        if isinstance(scene, dict)
        for line in scene.get("lines", [])
        if isinstance(line, dict) and str(line.get("text", "")).strip() and str(line.get("characterId", "")).strip()
    ]
def _requires_llm(request: deps.AiDirectionRequest) -> bool:
    return any((request.emoji_expressions, request.speech_rate, request.gap_seconds, request.stage_direction))
def _apply_removals(line: dict[str, Any], request: deps.AiDirectionRequest) -> bool:
    """Apply deterministic removals and report whether the audio itself changed."""
    render_changed = False
    if request.remove_emoji_expressions:
        text = str(line.get("text", ""))
        without_expressions = deps.strip_irodori_expression_emojis(text)
        if without_expressions != text:
            line["text"] = without_expressions
            render_changed = True
    if request.remove_speech_rate:
        render_changed |= line.pop("speechRate", None) is not None
    if request.remove_gap_seconds:
        line.pop("gapSeconds", None)
    if request.remove_stage_direction:
        render_changed |= line.pop("stageDirection", None) is not None
    return render_changed


def _apply_updates(request: deps.AiDirectionRequest, updates: list[dict[str, Any]]) -> list[str]:
    with deps.PROJECT_ROOT_LOCK:
        return _apply_updates_locked(request, updates)


def _apply_updates_locked(request: deps.AiDirectionRequest, updates: list[dict[str, Any]]) -> list[str]:
    latest = deps.read_project()
    updates_by_id = {update["id"]: update for update in updates}
    render_line_ids: list[str] = []
    for scene in latest.get("scenes", []):
        for line in scene.get("lines", []):
            line.pop("takesNeedRegeneration", None)
            update = updates_by_id.get(str(line.get("id")))
            if not update:
                continue
            if not request.overwrite_existing:
                for key in ("speechRate", "gapSeconds", "stageDirection"):
                    if key in update and line.get(key) not in (None, ""):
                        update.pop(key)
            render_changed = any(
                line.get(key) != update[key] for key in ("text", "speechRate", "stageDirection") if key in update
            )
            line.update({key: value for key, value in update.items() if key != "id"})
            render_changed |= _apply_removals(line, request)
            if render_changed and line.get("takes"):
                render_line_ids.append(str(line.get("id")))
    deps.write_project(latest)
    return render_line_ids



def direct_performance_chunk(
    request: deps.AiDirectionRequest,
    *,
    job_id: str,
    chunk: list[dict[str, Any]],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    cast_context: list[dict[str, Any]] | None = None,
    chunk_index: int,
    chunk_total: int,
    debug_directory: Path,
    completed_lines_before: int = 0,
    performance_total_lines: int | None = None,
    simultaneous_cues: bool = False, emoji_enabled_by_character: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Accept every usable field from one directing response."""
    allowed = set(request.allowed_emojis).intersection(deps.AI_PROPOSABLE_EMOJIS)
    if deps.draft_cancel_requested(job_id):
        raise deps.GenerationCancelled("AI演出をキャンセルしました。")
    deps.update_draft_job(
        job_id,
        performanceAttempt=1,
        message="LLMの応答を待っています",
    )
    aliases = {str(row["alias"]) for row in chunk}

    def report_progress(streamed: str) -> None:
        parsed_lines = len(aliases.intersection(_parse(streamed)))
        patch = {"receivedCharacters": len(streamed), "receivedRecords": parsed_lines}
        if performance_total_lines:
            completed = completed_lines_before + parsed_lines
            patch.update(
                performanceCompletedLines=completed,
                performanceTotalLines=performance_total_lines,
                message="演技設定を受信しています",
            )
            deps.advance_draft_progress(
                job_id,
                overall_progress=deps.draft_performance_overall_progress(completed, performance_total_lines),
            )
        deps.update_draft_job(job_id, **patch)

    content = _request_text(
        request,
        chunk,
        before,
        after,
        cast_context,
        job_id=job_id,
        debug_response_path=debug_directory / f"direction-chunk-{chunk_index:02d}-attempt-1.txt",
        on_progress=report_progress,
        simultaneous_cues=simultaneous_cues,
    )
    parsed = _parse(content)
    deps.update_draft_job(job_id, receivedCharacters=len(content), receivedRecords=len(parsed))
    updates = []
    values_by_row = deps.normalize_negative_gap_ownership(
        [(row, _record_values(parsed.get(row["alias"], []))) for row in chunk],
        default_gap=0.7, following_row=after[0] if after else None,
    )
    for row, values in zip(chunk, values_by_row, strict=True):
        if emoji_enabled_by_character is not None and not emoji_enabled_by_character.get(str(row.get("character_id", "")), False):
            values.pop("emoji", None)
        updates.append({"id": row["id"], **_performance_patch(request, row, values, allowed)})
    if simultaneous_cues and aliases.issubset(parsed):
        for update, row in zip(updates, chunk, strict=True):
            cue = _record_values(parsed.get(row["alias"], [])).get("cue", "").strip()
            if deps.CUE_MARKER.fullmatch(cue):
                update["simultaneous_marker"] = cue
    return updates


def run_ai_direction(job_id: str, request: deps.AiDirectionRequest) -> None:  # noqa: C901
    deps.DRAFT_LLM_THREAD_CONTEXT.job_id = job_id
    usage_card_id = deps.default_llm_card_id()
    stage = "対象行の確認"
    completed_chunks = 0
    all_updates: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    try:
        project = deps.read_project()
        spoken = _spoken(project)
        by_id = {str(line["id"]): (scene, line) for scene, line in spoken}
        if len(set(request.line_ids)) != len(request.line_ids) or any(item not in by_id for item in request.line_ids):
            raise RuntimeError("対象行が無効です。台本を開き直して選び直してください。")
        ordered = [item for item in spoken if str(item[1]["id"]) in set(request.line_ids)]
        positions = [index for index, (_, line) in enumerate(spoken) if str(line["id"]) in set(request.line_ids)]
        if positions != list(range(min(positions), max(positions) + 1)):
            raise RuntimeError("対象行は有効発話行の連続範囲で指定してください。")
        characters = {str(item.get("id")): str(item.get("name", "")) for item in project.get("characters", [])}
        adjacent = spoken[max(0, min(positions) - DIRECTION_CONTEXT_SIZE):max(positions) + DIRECTION_CONTEXT_SIZE + 1]
        character_ids = list(dict.fromkeys(str(line.get("characterId")) for _, line in [*ordered, *adjacent]))
        selected_characters = [item for item in project.get("characters", []) if str(item.get("id")) in character_ids]
        cast_alias_by_id = {character_id: chr(65 + index) for index, character_id in enumerate(character_ids)}
        cast_context = deps.draft_cast_context(selected_characters, cast_alias_by_id=cast_alias_by_id)
        rows = [
            {
                "alias": f"L{i}",
                "id": str(line["id"]),
                "character_id": str(line.get("characterId", "")),
                "emoji_allowed": request.emoji_expressions and emoji_enabled_for_cast(request, str(line.get("characterId", ""))),
                "name": characters.get(str(line.get("characterId")), "?"),
                "text": str(line.get("text", "")),
                "rate": line.get("speechRate", "未設定"),
                "gap": line.get("gapSeconds", "未設定"),
                "stage": str(line.get("stageDirection", "")),
            }
            for i, (_, line) in enumerate(ordered, 1)
        ]
        first = min(positions)

        def context(index: int) -> dict[str, Any] | None:
            if not 0 <= index < len(spoken):
                return None
            if first <= index < first + len(rows):
                return {**rows[index - first], "alias": "C"}
            _, line = spoken[index]
            return {
                "alias": "C",
                "character_id": str(line.get("characterId", "")),
                "name": characters.get(str(line.get("characterId")), "?"),
                "text": str(line.get("text", "")),
                "rate": line.get("speechRate", "未設定"),
                "gap": line.get("gapSeconds", "未設定"),
                "stage": str(line.get("stageDirection", "")),
            }

        if not _requires_llm(request):
            render_line_ids = _apply_updates(request, [{"id": row["id"]} for row in rows])
            deps.update_draft_job(
                job_id,
                status="completed",
                phase="completed",
                performanceCompletedLines=len(rows),
                renderLineIds=render_line_ids,
                message="選択した演出を削除しました。",
                completedAt=deps.now_ms(),
            )
            return

        deps.update_draft_job(job_id, status="generating", phase="direction", message="LLMからの応答を待っています…")
        debug_directory = deps.draft_debug_directory(job_id)
        profile = deps.build_direction_capability_profile(request)
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = profile
        deps.write_draft_debug_response(
            debug_directory / "direction-capability-profile.json",
            json.dumps(profile, ensure_ascii=False, indent=2),
        )
        maximum_chunk = direction_chunk_size(profile)
        cursor = 0
        chunk_index = 0
        while cursor < len(rows):
            chunk_index += 1
            chunk_start = first + cursor
            selected = None
            sizes = (*reversed(deps.DIRECTION_CHUNK_CANDIDATES), 5, 1)
            for size in dict.fromkeys(size for size in (maximum_chunk, *sizes) if size <= maximum_chunk):
                candidate = rows[cursor : cursor + size]
                before = [
                    item
                    for index in range(chunk_start - DIRECTION_CONTEXT_SIZE, chunk_start)
                    if (item := context(index))
                ]
                after_start = chunk_start + len(candidate)
                after = [
                    item
                    for index in range(after_start, after_start + DIRECTION_CONTEXT_SIZE)
                    if (item := context(index))
                ]
                output_tokens = _response_token_limit(candidate)
                input_tokens = deps.direction_input_token_estimate(candidate, before, after, cast_context)
                context_limit = deps.select_direction_context(
                    profile,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
                if context_limit is not None or profile.get("contextCeiling") is None:
                    selected = candidate, before, after
                    profile["directionChunkSize"] = len(candidate)
                    profile["chunkShrinkReason"] = (
                        f"推定要求が上限を超えるため{maximum_chunk}行から{len(candidate)}行へ縮小"
                        if len(candidate) < maximum_chunk
                        else ""
                    )
                    break
            if selected is None:
                raise RuntimeError("1行のAI演出プロンプトも利用可能なContextへ収まりません。")
            chunk, before, after = selected
            remaining = len(rows) - cursor
            chunk_total = chunk_index + max(0, (remaining - len(chunk) + maximum_chunk - 1) // maximum_chunk)
            stage = f"AI演出チャンク {chunk_index}/{chunk_total}"
            deps.write_draft_debug_response(
                debug_directory / f"direction-chunk-{chunk_index:02d}-profile.json",
                json.dumps(profile, ensure_ascii=False, indent=2),
            )
            try:
                updates = direct_performance_chunk(
                    request,
                    job_id=job_id,
                    chunk=chunk,
                    before=before,
                    after=after,
                    cast_context=cast_context,
                    chunk_index=chunk_index,
                    chunk_total=chunk_total,
                    debug_directory=debug_directory,
                    completed_lines_before=len(all_updates),
                    performance_total_lines=len(rows),
                )
            except RuntimeError:
                if profile.pop("retryDirectionChunk", False):
                    maximum_chunk = int(profile["directionChunkSize"])
                    chunk_index -= 1
                    continue
                raise
            all_updates.extend(updates)
            for row, update in zip(chunk, updates, strict=True):
                if "text" in update:
                    row["text"] = update["text"]
                if "speechRate" in update:
                    row["rate"] = update["speechRate"]
                if "gapSeconds" in update:
                    row["gap"] = update["gapSeconds"]
                if "stageDirection" in update:
                    row["stage"] = update["stageDirection"]
            deps.update_draft_job(
                job_id,
                performanceCompletedLines=len(all_updates),
                performanceTotalLines=len(rows),
                message="演技設定を検証しています",
            )
            completed_chunks = chunk_index
            cursor += len(chunk)
        stage = "演出の反映"
        render_line_ids = _apply_updates(request, all_updates)
        deps.update_draft_job(
            job_id,
            status="completed",
            phase="completed",
            renderLineIds=render_line_ids,
            message="AI演出を反映しました。",
            completedAt=deps.now_ms(),
        )
        deps.record_llm_usage(usage_card_id, "AI演出", True)
        return
    except deps.GenerationCancelled:
        deps.update_draft_job(
            job_id,
            status="cancelled",
            phase="cancelled",
            message="AI演出をキャンセルしました。台本は変更していません。",
            completedAt=deps.now_ms(),
        )
        deps.record_llm_usage(usage_card_id, "AI演出", False, "cancelled")
    except Exception as error:
        partial_applied_lines = 0
        partial_apply_error = ""
        render_line_ids: list[str] = []
        if stage.startswith("AI演出チャンク") and all_updates:
            try:
                render_line_ids = _apply_updates(request, all_updates)
                partial_applied_lines = len(all_updates)
            except Exception as apply_error:
                partial_apply_error = str(apply_error)
        try:
            failure_path = deps.draft_debug_directory(job_id) / "ai-direction-failure.json"
            deps.write_draft_debug_response(
                failure_path,
                json.dumps(
                    {
                        "stage": stage,
                        "completedChunks": completed_chunks,
                        "acceptedLines": len(all_updates),
                        "partialAppliedLines": partial_applied_lines,
                        "partialApplyError": partial_apply_error,
                        "errorType": type(error).__name__,
                        "error": str(error),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except OSError:
            pass
        deps.update_draft_job(
            job_id,
            status="failed",
            phase="failed",
            message=(
                f"AI演出を一部反映しました（適用済み {partial_applied_lines}行）。"
                if partial_applied_lines
                else "AI演出を反映しませんでした。"
            ),
            error=str(error),
            performanceCompletedLines=partial_applied_lines or len(all_updates),
            performanceTotalLines=len(rows),
            renderLineIds=render_line_ids,
            completedAt=deps.now_ms(),
        )
        deps.record_llm_usage(usage_card_id, "AI演出", False, type(error).__name__)
    finally:
        deps.DRAFT_LLM_THREAD_CONTEXT.job_id = None
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None
        with deps.DRAFT_LLM_RESPONSES_LOCK:
            deps.DRAFT_LLM_RESPONSES.pop(job_id, None)
deps.register(
    __name__,
    ["direct_performance_chunk", "run_ai_direction"],
)

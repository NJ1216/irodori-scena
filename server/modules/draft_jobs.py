from __future__ import annotations

from server.app_deps import Any
from server.registry import deps


def _reader_facing_description(value: Any, fallback: str) -> str:
    description = str(value or "").strip()
    labels = ("名前", "読み", "苗字", "ふりがな", "年齢", "性別", "職業", "一人称", "二人称", "誕生日")
    database_fields = sum(
        1 for label in labels if f"{label}:" in description or f"{label}：" in description
    )
    return fallback if database_fields >= 2 or any(
        description.startswith(f"{label}{separator}") for label in labels for separator in (":", "：")
    ) else description or fallback


def _script_cast_contexts(
    plan: dict[str, Any], cast_context: list[dict[str, Any]], cast_alias_by_id: dict[str, str]
) -> dict[str, dict[str, str]]:
    planned = plan.get("cast_contexts", {})
    by_alias = {str(item.get("cast", "")): item for item in cast_context}
    result: dict[str, dict[str, str]] = {}
    for cast_id, alias in cast_alias_by_id.items():
        source = by_alias.get(alias, {})
        fallback = str(source.get("reader_facing_introduction_seed", "")).strip() or "この台本の登場人物。"
        fallback_role = str(source.get("reader_facing_role_seed", "")).strip() or "登場人物"
        planned_context = planned.get(alias, {}) if isinstance(planned, dict) else {}
        role = str(planned_context.get("role", "")).strip() if isinstance(planned_context, dict) else ""
        description = planned_context.get("description", "") if isinstance(planned_context, dict) else ""
        result[cast_id] = {
            "role": role or fallback_role,
            "description": _reader_facing_description(description, fallback),
        }
    return result


def _direct_draft_chapters(
    job_id,
    request,
    repaired_chapters,
    chapters,
    cast_context,
    cast_alias_by_id,
    character_names_by_id,
    token_budget,
    debug_directory,
    title,
    script_cast_contexts,
) -> None:
    performance_state = ""
    directed_chunks: list[dict[str, Any]] = []
    total_lines = sum(len(item["dialogue"].get("lines", [])) for item in repaired_chapters)
    completed_lines = 0
    deps.update_draft_job(job_id, performanceCompletedLines=0, performanceTotalLines=total_lines)
    for index, item in enumerate(repaired_chapters):
        deps.ensure_draft_not_cancelled(job_id)
        lookahead = (
            repaired_chapters[index + 1]["dialogue"]["lines"][: deps.DRAFT_LOOKAHEAD_LINE_COUNT]
            if index + 1 < len(repaired_chapters)
            else []
        )
        deps.update_draft_job(
            job_id,
            phase="performance",
            message="LLMの応答を待っています",
            currentChunk=index + 1,
        )
        scenes = deps.direct_draft_performance(
            request,
            job_id=job_id,
            cast_context=cast_context,
            chapter=item["chapter"],
            dialogue=item["dialogue"],
            lookahead_lines=lookahead,
            cast_alias_by_id=cast_alias_by_id,
            prior_performance_state=performance_state,
            token_budget=token_budget,
            debug_directory=debug_directory,
            chapter_index=index,
            total_chapters=len(repaired_chapters),
            completed_lines_before=completed_lines,
            performance_total_lines=total_lines,
            should_cancel=lambda: deps.draft_cancel_requested(job_id),
            on_text_corrections=lambda count: deps.add_draft_text_corrections(job_id, count),
            allow_llm_fallback=False,
        )
        completed_lines += len(item["dialogue"].get("lines", []))
        deps.ensure_draft_not_cancelled(job_id)
        directed_chunks.append(
            {
                "scenes": scenes,
                "spoken": int(item["spoken"]),
                "discarded_duplicates": int(item["discarded_duplicates"]),
            }
        )
        performance_state = deps.compact_performance_state(scenes, character_names_by_id)
        deps.update_draft_job(job_id, performanceCompletedLines=completed_lines, message="演技設定を検証しています")
        deps.advance_draft_progress(job_id, overall_progress=deps.draft_performance_overall_progress(completed_lines, total_lines))
    deps.ensure_draft_not_cancelled(job_id)
    deps.append_directed_draft(
        job_id, title=title, chunks=directed_chunks, script_cast_contexts=script_cast_contexts,
    )


def _cancel_draft_job(job_id: str) -> None:
    deps.rollback_cancelled_draft(job_id)
    deps.update_draft_job(
        job_id,
        status="cancelled",
        phase="cancelled",
        message="生成をキャンセルしました。台本は変更していません。",
        completedAt=deps.now_ms(),
    )


def run_draft_job(job_id: str, request: deps.DraftRequest, characters: list[dict[str, Any]]) -> None:
    deps.run_forward_draft_job(job_id, request, characters)


deps.register(
    __name__,
    [
        "_cancel_draft_job",
        "_direct_draft_chapters",
        "_script_cast_contexts",
        "run_draft_job",
    ],
)

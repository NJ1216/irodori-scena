from __future__ import annotations

from typing import Any, Callable

from server.registry import deps

DEFAULT_CONTEXT_TOKENS = 4096


def activate_script_assistant_context(job_id: str, request: Any) -> None:
    deps.DRAFT_LLM_THREAD_CONTEXT.job_id = job_id
    deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = deps.build_direction_capability_profile(request)


def clear_script_assistant_context() -> None:
    deps.DRAFT_LLM_THREAD_CONTEXT.job_id = None
    deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None


def context_limit() -> int:
    profile = deps.active_draft_capability_profile()
    if isinstance(profile, dict):
        for key in ("effectiveContext", "contextCeiling"):
            value = profile.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    return DEFAULT_CONTEXT_TOKENS


def output_reservation(line_count: int) -> int:
    return min(8192, max(512, line_count * 190))


def fits(system: str, user: dict[str, Any], reserved_output: int) -> bool:
    estimate = deps.estimate_llm_input_tokens(system, user)
    # Keep this preflight identical to prepare_draft_llm_call(). Otherwise a
    # payload can pass local packing and then fail immediately before network
    # I/O, which was especially easy to hit with eight-cast rewrite context.
    minimum_output = 256
    return (
        estimate + max(minimum_output, reserved_output) + deps.DRAFT_CONTEXT_SAFETY_MARGIN
        <= context_limit()
    )


def largest_fitting_prefix(
    rows: list[dict[str, Any]], build_user: Callable[[list[dict[str, Any]]], dict[str, Any]], system: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return the largest non-empty ordered prefix whose exact prompt fits."""
    if not rows:
        return [], {"inputTokenEstimate": 0, "outputReservation": 0, "contextLimit": context_limit()}
    low, high, best = 1, len(rows), 0
    while low <= high:
        middle = (low + high) // 2
        user = build_user(rows[:middle])
        reserve = output_reservation(middle)
        if fits(system, user, reserve):
            best, low = middle, middle + 1
        else:
            high = middle - 1
    if best == 0:
        user = build_user(rows[:1])
        required = (
            deps.estimate_llm_input_tokens(system, user)
            + max(256, output_reservation(1))
            + deps.DRAFT_CONTEXT_SAFETY_MARGIN
        )
        raise RuntimeError(
            f"編集対象・近接・人物Contextがモデル上限へ収まりません（必要約{required}、上限{context_limit()}トークン）。"
        )
    selected = rows[:best]
    user = build_user(selected)
    return selected, {
        "inputTokenEstimate": deps.estimate_llm_input_tokens(system, user),
        "outputReservation": output_reservation(best), "contextLimit": context_limit(),
        "shrinkReason": "Context適合のため対象範囲を縮小" if best < len(rows) else "",
    }


deps.register(__name__, ["activate_script_assistant_context", "clear_script_assistant_context"])

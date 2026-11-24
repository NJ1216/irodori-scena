from __future__ import annotations

from server.app_deps import math, Any
from server.registry import deps


def minimum_acceptable_characters(target: int) -> int:
    return max(math.ceil(target * 0.95), target - 500)


def draft_generation_target(target: int) -> int:
    """Return the dialogue goal while keeping the author's duration target intact."""
    return (max(0, target) * 110 + 99) // 100


def first_packet_request(allocated_characters: int, max_block: int) -> tuple[int, str | None]:
    uncapped = math.ceil(max(0, allocated_characters) * deps.DRAFT_FIRST_PACKET_HEADROOM)
    requested = min(max_block, deps.DRAFT_DIALOGUE_REQUEST_CEILING, uncapped)
    return requested, "character_ceiling" if requested < uncapped else None


def second_packet_request(*, generation_target: int, first_accepted: int,
                          first_requested: int, max_block: int) -> tuple[int, float, int, int, str | None]:
    """Correct the final normal packet from this job's first accepted yield."""
    remaining = max(0, generation_target - first_accepted)
    observed = first_accepted / first_requested if first_requested > 0 else 0.0
    measured = max(deps.DRAFT_MIN_YIELD_RATIO, min(deps.DRAFT_MAX_YIELD_RATIO, observed))
    uncapped = math.ceil(remaining / measured * deps.DRAFT_FORWARD_REQUEST_HEADROOM)
    requested = min(max_block, deps.DRAFT_DIALOGUE_REQUEST_CEILING, uncapped)
    return requested, measured, remaining, uncapped, "character_ceiling" if requested < uncapped else None


def planned_draft_blocks(target: int, max_block: int, initial_yield: float) -> int:
    safe_yield = max(0.40, min(1.00, initial_yield))
    return max(1, math.ceil(target / max(1, max_block * safe_yield)))


def resilient_planned_draft_blocks(target: int, max_block: int) -> int:
    """Pre-plan enough distinct blocks to reach target at the accepted-yield floor."""
    base = math.ceil(target / max(1, max_block * 0.25))
    return max(1, base + (1 if base > 1 else 0))


def required_draft_developments(target: int, max_block: int, chapter_count: int) -> int:
    """Size technical generation work without exposing it as story chapters."""
    capacity_slots = math.ceil(target / max(1, max_block * 0.25))
    return max(1, chapter_count, capacity_slots)


def maximum_dialogue_calls(development_count: int) -> int:
    return development_count + max(2, math.ceil(development_count * 0.20))


def final_block_has_floor_capacity(*, accepted: int, target: int, max_block: int) -> bool:
    return accepted + math.floor(max_block * 0.25) >= target


def forward_block_schedule(
    *, index: int, planned: int, core: int, accepted: int, target: int, max_block: int,
) -> tuple[bool, int, bool]:
    is_final = index == planned - 1
    is_reserve = core - 1 <= index < planned - 1
    skip = is_reserve and final_block_has_floor_capacity(
        accepted=accepted, target=target, max_block=max_block,
    )
    if index < core - 1:
        remaining = core - index
    elif is_final:
        remaining = 1
    else:
        remaining = planned - index
    return skip, remaining, is_reserve


def next_forward_request(
    *, target: int, accepted: int, remaining_blocks: int, required: int,
    requested_total: int, accepted_total: int, max_block: int,
) -> tuple[int, float, int]:
    remaining = max(0, target - accepted)
    accepted_goal = max(required, math.ceil(remaining / max(1, remaining_blocks)))
    observed = accepted_total / max(1, requested_total)
    current_yield = max(0.25, min(1.00, observed))
    requested = min(
        max_block,
        math.ceil(accepted_goal / current_yield * deps.DRAFT_FORWARD_REQUEST_HEADROOM),
    )
    return requested, current_yield, accepted_goal


def validate_forward_plan(plan: dict[str, Any], planned_blocks: int, single_block: bool) -> list[dict[str, Any]]:
    chapters = plan.get("chapters") if isinstance(plan, dict) else None
    if not isinstance(chapters, list) or len(chapters) != planned_blocks:
        raise ValueError("必要な生成ブロック数を満たす構成を取得できませんでした。")
    minimum_beats = max(1, int(plan.get("_minimum_beats_per_block", 1)))
    for index, block in enumerate(chapters):
        if not isinstance(block, dict):
            raise ValueError("生成ブロックの構成が不正です。")
        beats = block.get("beats")
        if not str(block.get("opening_state", "")).strip() or not str(block.get("closing_state", "")).strip():
            raise ValueError(f"生成ブロック{index + 1}の開始・終了状態が不足しています。")
        if not isinstance(beats, list) or len([beat for beat in beats if str(beat).strip()]) < minimum_beats:
            raise ValueError(f"生成ブロック{index + 1}の必須展開が不足しています。")
        if single_block and not any(str(item).strip() for item in block.get("supplement_beats", [])):
            raise ValueError("短尺台本の追加展開が構成されていません。")
    return chapters


deps.register(__name__, [
    "draft_generation_target", "first_packet_request", "second_packet_request",
    "maximum_dialogue_calls", "required_draft_developments",
    "minimum_acceptable_characters", "next_forward_request", "planned_draft_blocks",
    "resilient_planned_draft_blocks",
    "final_block_has_floor_capacity",
    "forward_block_schedule",
    "validate_forward_plan",
])

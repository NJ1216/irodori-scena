"""Bounded, duration-aware dialogue packets independent of story chapter count."""
from __future__ import annotations

import math

from server.registry import deps


def duration_character_target(request) -> int:
    # Use the same 5.5 chars/sec basis as estimated_draft_seconds, allowing for
    # ordinary 80-character utterances and their configured inter-line gaps.
    per_character = 1 / (5.5 * request.speech_rate) + max(0, request.line_gap) / 80
    return max(160, round(request.target_minutes * 60 / per_character))


def packet_call_limit(target: int, max_block: int) -> int:
    return max(2, math.ceil(target / max(160, max_block)))


def predicted_packet_calls(planned_targets: dict[str, int], max_block: int,
                           max_sources: int | None = None) -> int:
    """Estimate calls by packing complete semantic sources in plan order."""
    calls, used, sources = 0, 0, 0
    for target in planned_targets.values():
        size = max(1, int(target))
        if used and (used + size > max_block or (max_sources is not None and sources >= max_sources)):
            calls, used, sources = calls + 1, 0, 0
        used += size
        sources += 1
        if used >= max_block:
            calls, used, sources = calls + 1, 0, 0
    return calls + int(bool(used))


def next_packet(*, pending, calls, accepted, generation_target, max_block, max_calls,
                planned_targets, batch_size=None):
    remaining = [item for chapter in pending for item in chapter]
    slots = max(1, max_calls - calls)
    limit = max(1, int(batch_size or math.ceil(len(remaining) / slots)))
    selected, planned = [], 0
    for item in remaining:
        source = item.split("|", 1)[0]
        size = max(1, int(planned_targets.get(source, 0)))
        if selected and (len(selected) >= limit or planned + size > max_block):
            break
        selected.append(item)
        planned += size
    goal = max(0, generation_target - accepted)
    goal = min(goal, planned or math.ceil(goal / slots))
    requested = min(max_block, max(80, goal))
    return selected, requested, goal, None, requested, None, slots == 1


def accepted_duration(drafted, request) -> float:
    scenes = []
    for item in drafted:
        lines = []
        for row in item["dialogue"].get("lines", []):
            values = row.get("integrated_direction") or {}
            try:
                rate = float(values.get("rate", request.speech_rate))
                gap = float(values.get("gap", request.line_gap))
            except (TypeError, ValueError):
                rate, gap = request.speech_rate, request.line_gap
            if not math.isfinite(rate) or rate <= 0:
                rate = request.speech_rate
            if not math.isfinite(gap) or gap < 0:
                gap = request.line_gap
            lines.append({"text": row["text"], "speechRate": rate, "gapSeconds": gap})
        scenes.append({"lines": lines})
    return deps.estimated_draft_seconds(scenes)


def remaining_character_target(drafted, request, accepted: int, original: int) -> int:
    seconds = accepted_duration(drafted, request)
    if seconds <= 0 or accepted <= 0:
        return original
    return accepted + max(0, round((request.target_minutes * 60 - seconds) * accepted / seconds))


def adjust_for_observed_yield(targets, history, capacity, final_source, final_target):
    """Budget upcoming content from observed yield; never lengthen the ending."""
    requested = sum(item.get("requested", 0) for item in history)
    accepted = sum(item.get("accepted", 0) for item in history)
    if requested <= 0:
        return targets
    ratio = min(1, max(deps.DRAFT_MIN_YIELD_RATIO, accepted / requested))
    ending = min(targets.get(final_source, 0), final_target)
    work = {source: math.ceil(size / ratio) for source, size in targets.items() if source != final_source}
    work = deps.allocate_source_targets(list(work), min(sum(work.values()), max(0, capacity - ending)), work)
    return {source: ending if source == final_source else work[source] for source in targets}

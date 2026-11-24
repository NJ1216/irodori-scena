from __future__ import annotations

from typing import Any
from server.registry import deps


def estimated_draft_seconds(scenes: list[dict[str, Any]]) -> float:
    unit_durations: list[float] = []
    gaps: list[float] = []
    for scene in scenes:
        for cue in deps.cue_groups(scene.get("lines", [])):
            durations = []
            for line in cue:
                rate = deps._strict_float(line.get("speechRate")) or 1.0
                text = str(line.get("text", ""))
                events = sum(text.count(emoji) for emoji in deps.TAIL_EVENT_EMOJIS)
                durations.append(len(deps.strip_draft_emojis(text)) / max(1.0, 5.5 * rate) + events * 0.45)
            unit_durations.append(max(durations, default=0.0))
            gap = deps._strict_float(cue[0].get("gapSeconds"))
            gaps.append(max(-9999.0, min(9999.0, gap if gap is not None else 0.0)))
    if not unit_durations:
        return 0.0
    starts, _ = deps.effective_unit_starts(unit_durations, gaps)
    return round(starts[-1] + unit_durations[-1], 1)

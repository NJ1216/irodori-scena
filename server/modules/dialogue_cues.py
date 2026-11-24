from __future__ import annotations

import math
from typing import Any, Iterable

from server.registry import deps


def cue_key(line: dict[str, Any]) -> str:
    value = line.get("cueId")
    return str(value).strip() if isinstance(value, str) else ""


def cue_groups(lines: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Return consecutive cue units. Ungrouped lines are one-line cue units."""
    groups: list[list[dict[str, Any]]] = []
    for line in lines:
        key = cue_key(line)
        if key and groups and cue_key(groups[-1][0]) == key:
            groups[-1].append(line)
        else:
            groups.append([line])
    return groups


def normalize_start_offset(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number < 0:
        return 0.0
    return round(min(number, 9999.0), 3)


def normalize_target_duration(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(max(0.5, min(30.0, number)), 1)


def _take_speech_rate(value: Any) -> float:
    if isinstance(value, bool):
        return 1.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(0.5, min(2.0, number)) if math.isfinite(number) else 1.0


def linked_cue_target_duration(
    project: dict[str, Any], line: dict[str, Any], speech_rate: float,
) -> float | None:
    """Scale the earliest other selected take by the requested relative rate."""
    candidates: list[tuple[float, int, dict[str, Any]]] = []
    line_id = str(line.get("id", ""))
    for scene in project.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        cue = cue_for_line(scene, line_id)
        if len(cue) < 2:
            continue
        for order, member in enumerate(cue):
            if str(member.get("id", "")) == line_id:
                continue
            selected_id = str(member.get("selectedTakeId") or "")
            take = next((item for item in member.get("takes", []) if str(item.get("id", "")) == selected_id), None)
            if not isinstance(take, dict):
                continue
            duration = normalize_target_duration(take.get("durationSeconds"))
            if duration is None:
                continue
            created_at = take.get("createdAt")
            created = float(created_at) if isinstance(created_at, (int, float)) else float("inf")
            candidates.append((created, order, take))
        break
    if not candidates:
        return None
    take = min(candidates, key=lambda item: (item[0], item[1]))[2]
    settings = take.get("settings") if isinstance(take.get("settings"), dict) else {}
    basis_rate = _take_speech_rate(take.get("speechRate", settings.get("speechRate")))
    duration = float(take["durationSeconds"])
    return normalize_target_duration(duration * basis_rate / speech_rate)


def normalize_scene_cues(scene: dict[str, Any]) -> None:
    """Repair corrupt cue metadata without dropping dialogue or takes."""
    raw = scene.get("lines")
    if not isinstance(raw, list):
        scene["lines"] = []
        return
    lines = [line for line in raw if isinstance(line, dict)]
    for line in lines:
        target_duration = normalize_target_duration(line.get("targetDurationSeconds"))
        if target_duration is None:
            line.pop("targetDurationSeconds", None)
        else:
            line["targetDurationSeconds"] = target_duration
    occurrences: dict[str, list[int]] = {}
    for index, line in enumerate(lines):
        key = cue_key(line)
        if key:
            occurrences.setdefault(key, []).append(index)
    valid_ids = {
        key for key, indexes in occurrences.items()
        if len(indexes) >= 2 and indexes == list(range(indexes[0], indexes[-1] + 1))
    }
    for group in cue_groups(lines):
        key = cue_key(group[0])
        if key not in valid_ids:
            for line in group:
                line.pop("cueId", None)
                line.pop("startOffsetSeconds", None)
            continue
        seen_cast: set[str] = set()
        for member_index, line in enumerate(group):
            cast = str(line.get("characterId", ""))
            if cast and cast in seen_cast:
                line.pop("cueId", None)
                line.pop("startOffsetSeconds", None)
                continue
            if cast:
                seen_cast.add(cast)
            line["startOffsetSeconds"] = normalize_start_offset(line.get("startOffsetSeconds"))
            if member_index:
                line.pop("enabled", None)
                line.pop("gapSeconds", None)
    # A duplicate cast may split a former group. Normalize any resulting singleton.
    for group in cue_groups(lines):
        if cue_key(group[0]) and len(group) == 1:
            group[0].pop("cueId", None)
            group[0].pop("startOffsetSeconds", None)
    scene["lines"] = lines


def normalize_project_cues(project: dict[str, Any]) -> None:
    for scene in project.get("scenes", []):
        if isinstance(scene, dict):
            normalize_scene_cues(scene)


def finalize_draft_simultaneous_cues(lines: list[dict[str, Any]]) -> int:
    """Issue durable cue IDs only after every generated line is fully directed."""
    candidates: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        candidate = str(line.pop("simultaneous_candidate_id", "")).strip()
        if candidate:
            candidates.setdefault(candidate, []).append(line)
    count = 0
    for members in candidates.values():
        indexes = [lines.index(line) for line in members]
        if not (2 <= len(members) <= 8 and indexes == list(range(indexes[0], indexes[-1] + 1))):
            continue
        if len({str(line.get("characterId", "")) for line in members}) != len(members):
            continue
        cue_id = deps.new_id("cue")
        trailing_gap = members[-1].get("gapSeconds")
        for member in members:
            member["cueId"] = cue_id
            member["startOffsetSeconds"] = 0.0
            member.pop("gapSeconds", None)
            member.pop("targetDurationSeconds", None)
        if trailing_gap is not None:
            members[0]["gapSeconds"] = trailing_gap
        count += 1
    return count


def cue_for_line(scene: dict[str, Any], line_id: str) -> list[dict[str, Any]]:
    for group in cue_groups(scene.get("lines", [])):
        if any(str(line.get("id", "")) == line_id for line in group):
            return group
    return []


deps.register(__name__, ["cue_for_line", "cue_groups", "cue_key", "finalize_draft_simultaneous_cues", "linked_cue_target_duration", "normalize_project_cues", "normalize_scene_cues", "normalize_start_offset", "normalize_target_duration"])

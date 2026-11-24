"""Project-wide placement. Unknown durations are lower bounds, never estimates."""

from __future__ import annotations

import hashlib
import json
import math
import wave
from fastapi import HTTPException
from typing import Any

from server.registry import deps
from server.modules.timeline_identity import audio_identity


def unit_starts(durations: list[float], gaps: list[float]) -> tuple[list[float], list[float]]:
    starts: list[float] = []
    effective: list[float] = []
    for index, _duration in enumerate(durations):
        previous_end = starts[-1] + max(0, durations[index - 1]) if starts else 0
        start = max(0, previous_end + (gaps[index - 1] if index and index <= len(gaps) else 0))
        starts.append(start)
        if index:
            effective.append(start - previous_end)
    return starts, effective


def place_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure frame/second agnostic placement used by shared fixtures."""
    result = []
    start, dependencies = 0.0, []
    for unit in units:
        members = unit["members"]
        known = all(member.get("duration") is not None for member in members)
        duration = max((member.get("offset", 0) + (member.get("duration") or 0) for member in members), default=0)
        result.append(
            {
                **unit,
                "start": start,
                "duration": duration,
                "resolved": not dependencies and known,
                "startResolved": not dependencies,
                "dependencies": list(dependencies),
            }
        )
        dependencies = [*dependencies, *(member["id"] for member in members if member.get("duration") is None)]
        start = max(0, start + duration + unit.get("gap", 0))
    return result


def _member(line: dict[str, Any], grouped: bool, rate: int) -> dict[str, Any]:
    take = deps.selected_take_record(line)
    member = {
        "id": str(line["id"]),
        "offset": round(deps.normalize_start_offset(line.get("startOffsetSeconds")) * rate) if grouped else 0,
        "duration": None,
        "takeId": str((take or {}).get("id", "")),
        "signature": None,
        "path": None,
    }
    if take:
        try:
            path = deps.take_audio_path(take)
            with wave.open(str(path), "rb") as reader:
                if reader.getframerate() != rate:
                    raise HTTPException(422, "Timeline inputs must share a sample rate.")
                member["duration"] = reader.getnframes()
                member["channels"] = reader.getnchannels()
            member.update(path=str(path), signature=audio_identity(path))
        except (OSError, EOFError, wave.Error, RuntimeError):
            member.update(duration=None, signature=None, path=None)
    return member


def project_timeline(project: dict[str, Any]) -> dict[str, Any]:
    cues = [cue for scene in project.get("scenes", []) for cue in deps.cue_groups(scene.get("lines", []))]
    cues = [
        [
            line
            for line in cue
            if line.get("enabled") is not False and str(line.get("text", "")).strip() and line.get("characterId")
        ]
        for cue in cues
    ]
    cues = [cue for cue in cues if cue]
    rate = 48000
    for cue in cues:
        for line in cue:
            take = deps.selected_take_record(line)
            if take:
                try:
                    with wave.open(str(deps.take_audio_path(take)), "rb") as reader:
                        rate = reader.getframerate()
                    break
                except (OSError, EOFError, wave.Error, RuntimeError):
                    continue
        else:
            continue
        break
    units = []
    default_gap = project.get("settings", {}).get("lineGap", 0.7)
    for cue in cues:
        value = deps._strict_float(cue[0].get("gapSeconds"))
        units.append(
            {
                "id": str(cue[0]["id"]),
                "gap": round((default_gap if value is None else value) * rate),
                "members": [_member(line, bool(cue[0].get("cueId")), rate) for line in cue],
            }
        )
    placed = place_units(units)
    signature = hashlib.sha256(json.dumps(placed, sort_keys=True).encode()).hexdigest()
    return {
        "planId": signature,
        "generation": project.get("revision", 0),
        "projectId": project.get("id"),
        "sampleRate": rate,
        "units": placed,
        "resolved": all(unit["resolved"] for unit in placed),
        "endFrame": max((unit["start"] + unit["duration"] for unit in placed), default=0),
    }


def interval_inputs(
    plan: dict[str, Any], start: int, end: int, targets: set[str] | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    halo = max(26, math.ceil(plan["sampleRate"] * 0.15))
    inputs, needed = [], set()
    for unit in plan["units"]:
        for member in unit["members"]:
            if targets is not None and member["id"] not in targets:
                continue
            onset = unit["start"] + member.get("offset", 0)
            if onset >= end + halo:
                continue
            if not unit["startResolved"]:
                needed.update(unit["dependencies"])
            if member["duration"] is None:
                needed.add(member["id"])
            elif not unit["startResolved"] or onset + member["duration"] > start - halo:
                inputs.append({**member, "start": onset})
    order = [m["id"] for u in plan["units"] for m in u["members"]]
    return inputs, [line_id for line_id in order if line_id in needed]


def resolved_prefix_end(plan: dict[str, Any], start: int, end: int, targets: set[str] | None) -> int:
    """A partially ready logical second may publish only its safe leading frames."""
    halo = max(26, math.ceil(plan["sampleRate"] * 0.15))
    earliest = end
    for unit in plan["units"]:
        for member in unit["members"]:
            if targets is not None and member["id"] not in targets:
                continue
            if not unit["startResolved"] or member["duration"] is None:
                earliest = min(earliest, int(unit["start"] + member.get("offset", 0)) - halo)
    return earliest if earliest > start else end


def target_end(plan: dict[str, Any], targets: set[str] | None) -> int | None:
    ends = []
    for unit in plan["units"]:
        for member in unit["members"]:
            if targets is not None and member["id"] not in targets:
                continue
            if not unit["startResolved"] or member["duration"] is None:
                return None
            ends.append(int(unit["start"] + member.get("offset", 0) + member["duration"]))
    return max(ends, default=0)

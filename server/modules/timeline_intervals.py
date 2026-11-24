"""Content-addressed, bounded-memory interval rendering shared by playback/export."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Callable

from server.native_processing import render_timeline_wav
from server.registry import deps
from server.modules.timeline_identity import audio_identity
from server.modules.timeline import interval_inputs

_LOCKS = [threading.Lock() for _ in range(32)]

ALGORITHM = "timeline-v1-finite150ms-overlap-only-duck3db-ramp50ms-sinc4x16-bound-limit1db"


def describe_interval(plan: dict[str, Any], start: int, end: int, targets: set[str] | None = None) -> dict[str, Any]:
    inputs, missing = interval_inputs(plan, start, end, targets)
    rate = plan["sampleRate"]
    signature = hashlib.sha256(
        json.dumps(
            {
                "algorithm": ALGORITHM,
                "inputs": inputs,
                "start": start,
                "end": end,
                "rate": rate,
                "targets": sorted(targets)
                if targets is not None
                else sorted(m["id"] for u in plan["units"] for m in u["members"]),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    output = deps.MEDIA_ROOT / "cache" / "timeline-v1" / f"{signature}.wav"
    audible = any(item["start"] < end and item["start"] + item["duration"] > start for item in inputs)
    status = "waiting-input" if missing else "silence" if not audible else "ready" if output.is_file() else "queued"
    return {
        "intervalId": signature,
        "planId": plan["planId"],
        "generation": plan["generation"],
        "startFrame": start,
        "endFrame": end,
        "sampleRate": rate,
        "status": status,
        "dependencyLineIds": missing,
        "inputs": inputs,
        "targets": sorted(targets) if targets is not None else None,
        "output": str(output),
        "audioUrl": deps.media_url(output) if status == "ready" else None,
        "events": [
            {"lineId": item["id"], "startFrame": item["start"], "endFrame": item["start"] + item["duration"]}
            for item in inputs
            if item["start"] < end and item["start"] + item["duration"] > start
        ],
    }


def _render_interval(interval: dict[str, Any], should_cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
    inputs = interval["inputs"]
    for item in inputs:
        if audio_identity(Path(item["path"])) != item["signature"]:
            return {**interval, "status": "stale"}
    channels = {item["channels"] for item in inputs}
    if len(channels) > 1:
        raise ValueError("Timeline inputs must share a channel count.")
    output = Path(interval["output"])
    render_timeline_wav(
        [(Path(item["path"]), int(item["start"]), int(item["duration"])) for item in inputs],
        int(interval["startFrame"]),
        int(interval["endFrame"]),
        interval["sampleRate"],
        next(iter(channels), 1),
        output,
        should_cancel,
    )
    for item in inputs:
        if audio_identity(Path(item["path"])) != item["signature"]:
            output.unlink(missing_ok=True)
            return {**interval, "status": "stale"}
    return {**interval, "status": "ready", "audioUrl": deps.media_url(output)}


def render_interval(interval: dict[str, Any], should_cancel: Callable[[], bool] | None = None) -> dict[str, Any]:
    lock = _LOCKS[int(interval["intervalId"][:8], 16) % len(_LOCKS)]
    with lock:
        if should_cancel and should_cancel():
            raise InterruptedError("Timeline rendering cancelled.")
        if Path(interval["output"]).is_file():
            deps.persist_derived_cache(Path(interval["output"]), interval)
            return {**interval, "status": "ready", "audioUrl": deps.media_url(Path(interval["output"]))}
        result = _render_interval(interval, should_cancel)
        if result["status"] == "ready":
            deps.persist_derived_cache(Path(interval["output"]), interval)
        if should_cancel and should_cancel():
            # A fully published immutable file may be reused by the next request.
            raise InterruptedError("Timeline rendering cancelled.")
        return result


def public_interval(interval: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in interval.items() if key not in {"inputs", "output", "targets"}}


def background_intervals(plan: dict[str, Any]):
    """Visit audible seconds only, with a heap bounded by the number of voices."""
    import heapq

    rate = plan["sampleRate"]
    ranges = []
    for unit in plan["units"]:
        if not unit["startResolved"]:
            continue
        for member in unit["members"]:
            if member["duration"]:
                start = int(unit["start"] + member["offset"])
                heapq.heappush(ranges, (start // rate, (start + member["duration"] - 1) // rate))
    previous = -1
    while ranges:
        second, last = heapq.heappop(ranges)
        if second < last:
            heapq.heappush(ranges, (second + 1, last))
        if second == previous:
            continue
        previous = second
        end = min((second + 1) * rate, int(plan["endFrame"])) if plan["resolved"] else (second + 1) * rate
        yield describe_interval(plan, second * rate, end)

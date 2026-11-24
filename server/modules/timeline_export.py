"""Export through the same frame intervals as continuous playback."""

from __future__ import annotations

import wave
from pathlib import Path
from typing import Any, Callable
from server.registry import deps
from server.modules.timeline import project_timeline
from server.modules.timeline_intervals import describe_interval, render_interval


def write_timeline_wav(
    plan: dict[str, Any], output: Path, should_cancel: Callable[[], bool] | None = None, targets: set[str] | None = None
) -> None:
    if not plan["resolved"]:
        raise ValueError("Timeline inputs are not ready.")
    rate = plan["sampleRate"]
    channels = {member.get("channels", 1) for unit in plan["units"] for member in unit["members"]}
    if len(channels) > 1:
        raise ValueError("Timeline inputs must share a channel count.")
    channel_count = next(iter(channels), 1)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".timeline.tmp.wav")
    try:
        with wave.open(str(temporary), "wb") as writer:
            writer.setparams((channel_count, 2, rate, 0, "NONE", "not compressed"))
            for start in range(0, int(plan["endFrame"]), rate):
                if should_cancel and should_cancel():
                    raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
                interval = describe_interval(plan, start, min(start + rate, int(plan["endFrame"])), targets)
                if interval["status"] == "silence":
                    writer.writeframes(b"\x00" * (int(interval["endFrame"]) - start) * channel_count * 2)
                    continue
                if interval["status"] != "ready":
                    interval = render_interval(interval, should_cancel)
                if interval["status"] != "ready":
                    raise ValueError("Timeline changed during export.")
                with wave.open(interval["output"], "rb") as reader:
                    writer.writeframes(reader.readframes(reader.getnframes()))
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def export_timeline(project: dict[str, Any], lines: list[Any]) -> tuple[dict[str, Any], list[tuple[str, float, float]]]:
    plan = project_timeline(project)
    texts = {str(item.line["id"]): item.text for item in lines}
    rate = plan["sampleRate"]
    entries = []
    for unit in plan["units"]:
        for member in unit["members"]:
            if member["id"] not in texts:
                continue
            if member["duration"] is None or not unit["startResolved"]:
                raise ValueError("Subtitle timing is not ready.")
            start = (unit["start"] + member["offset"]) / rate
            entries.append((texts[member["id"]], start, start + member["duration"] / rate))
    entries.sort(key=lambda entry: entry[1])
    return plan, entries

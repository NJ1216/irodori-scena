from __future__ import annotations

import wave
from pathlib import Path
from typing import Callable
from server.modules.timeline_identity import audio_identity
from server.modules.timeline import place_units
from server.modules.timeline_export import write_timeline_wav


def join_wav_files(
    inputs: list[tuple[Path, float]],
    output: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
    overlap_files: list[Path | None] | None = None,
) -> None:
    """Legacy input adapter. Adjacent mix files are never reused by the timeline."""
    if not inputs:
        raise RuntimeError("There are no dialogue takes to export.")
    units, formats = [], set()
    for index, (path, gap) in enumerate(inputs):
        with wave.open(str(path), "rb") as reader:
            rate, channels, duration = reader.getframerate(), reader.getnchannels(), reader.getnframes()
        formats.add((rate, channels))
        units.append({"id": str(index), "gap": round(gap * rate), "members": [{"id": str(index), "path": str(path), "offset": 0,
                      "duration": duration, "channels": channels, "signature": audio_identity(path)}]})
    if len(formats) != 1:
        raise RuntimeError("All takes must use the same sample rate and channel count to export together.")
    placed = place_units(units)
    plan = {"units": placed, "planId": "export", "generation": 0, "resolved": True, "sampleRate": rate,
            "endFrame": max(unit["start"] + unit["duration"] for unit in placed)}
    write_timeline_wav(plan, output, should_cancel)

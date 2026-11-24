"""Original NumPy cue mixer retained only for native comparison fixtures."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from tools.pcm_analysis import decode_pcm as _decode_pcm, integrated_level as _integrated_level, true_peak as _true_peak


TRUE_PEAK_LIMIT = 10 ** (-1 / 20)


def mix_pcm_members(members: list[tuple[Path, float]], output: Path) -> float:
    decoded = [(_decode_pcm(path), max(0.0, offset)) for path, offset in members]
    rates = {item[0][1] for item in decoded}
    channels = {item[0][0].shape[1] for item in decoded}
    if len(rates) != 1 or len(channels) != 1:
        raise ValueError("Cue members must use the same sample rate and channel count.")
    rate, channel_count = rates.pop(), channels.pop()
    total = max(round(offset * rate) + len(samples) for ((samples, _rate), offset) in decoded)
    mixed = np.zeros((total, channel_count), dtype=np.float32)
    reference = 0.0
    for ((samples, _rate), offset) in decoded:
        start = round(offset * rate)
        mixed[start:start + len(samples)] += samples
        reference = max(reference, _integrated_level(samples) or 0.0)
    level = _integrated_level(mixed)
    if reference > 0 and level and level > 0:
        mixed *= reference / level
    peak = _true_peak(mixed)
    if peak > TRUE_PEAK_LIMIT:
        mixed *= TRUE_PEAK_LIMIT / peak
    pcm = np.round(np.clip(mixed, -1, 32767 / 32768) * 32768).astype("<i2")
    with wave.open(str(output), "wb") as writer:
        writer.setparams((channel_count, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(pcm.tobytes())
    return total / rate

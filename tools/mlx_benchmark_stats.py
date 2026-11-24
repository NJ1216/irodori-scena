"""Pure-Python statistics for the MLX TTS benchmark (no MLX import)."""

from __future__ import annotations

import hashlib
import math
import statistics
import struct
from collections.abc import Sequence


def summarize(values: Sequence[float]) -> dict[str, float]:
    if not values:
        raise ValueError("summarize needs at least one value.")
    ordered = sorted(float(value) for value in values)
    return {
        "median": statistics.median(ordered),
        # Same nearest-rank p95 as tools/validate_mps_adapter.py.
        "p95": ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)],
        "min": ordered[0],
        "max": ordered[-1],
        "runs": len(ordered),
    }


def snr_db(reference: Sequence[float], candidate: Sequence[float]) -> float:
    if len(reference) != len(candidate):
        raise ValueError("Audio lengths differ; SNR is undefined.")
    signal = sum(float(value) ** 2 for value in reference)
    noise = sum((float(a) - float(b)) ** 2 for a, b in zip(reference, candidate, strict=True))
    if noise == 0:
        return math.inf
    if signal == 0:
        return -math.inf
    return 10 * math.log10(signal / noise)


def _pcm16(value: float) -> int:
    return max(-32768, min(32767, int(round(float(value) * 32767))))


def pcm_sha256(samples: Sequence[float]) -> str:
    """Hash the PCM16 bytes a saved WAV would contain."""
    data = struct.pack(f"<{len(samples)}h", *(_pcm16(value) for value in samples))
    return hashlib.sha256(data).hexdigest()

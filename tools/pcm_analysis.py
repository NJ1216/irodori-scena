"""PCM analysis for audio reference tests and listening tools (development only; needs numpy).

The app mixes audio in scena_native; these helpers measure its output independently.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def decode_pcm(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as reader:
        channels, width, rate = reader.getnchannels(), reader.getsampwidth(), reader.getframerate()
        raw = reader.readframes(reader.getnframes())
    if width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768
    elif width == 3:
        data = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = data[:, 0] | data[:, 1] << 8 | data[:, 2] << 16
        samples = ((values ^ 0x800000) - 0x800000).astype(np.float32) / 8388608
    elif width == 4:
        samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648
    else:
        raise ValueError(f"Unsupported PCM sample width: {width}")
    return samples.reshape(-1, channels), rate


def integrated_level(samples: np.ndarray) -> float | None:
    mono = np.mean(samples, axis=1)
    if mono.size == 0:
        return None
    block = max(1, round(0.4 * 48_000))
    powers = [float(np.mean(mono[index : index + block] ** 2)) for index in range(0, mono.size, block)]
    audible = [power for power in powers if power > 10 ** (-70 / 10)]
    if not audible:
        return None
    ungated = float(np.mean(audible))
    gated = [power for power in audible if power >= ungated / 10]
    return float(np.sqrt(np.mean(gated or audible)))


def true_peak(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    if len(samples) < 2:
        return float(np.max(np.abs(samples)))
    positions = np.arange(len(samples), dtype=np.float64)
    oversampled = np.arange(0, len(samples) - 1 + 0.25, 0.25)
    return max(
        float(np.max(np.abs(np.interp(oversampled, positions, samples[:, channel]))))
        for channel in range(samples.shape[1])
    )

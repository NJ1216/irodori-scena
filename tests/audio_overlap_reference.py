"""Float32 reference used only to compare the native adaptive overlap renderer."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


TRUE_PEAK_LIMIT = 10 ** (-1 / 20)
GAIN_RAMP_SECONDS = 0.01
PRE_ROLL_SECONDS = 0.05
LIMITER_LOOKAHEAD_SECONDS = 0.005
LIMITER_RELEASE_SECONDS = 0.06
MINIMUM_PREVIOUS_GAIN = 10 ** (-3 / 20)


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


def mix(previous: np.ndarray, following: np.ndarray, rate: int) -> tuple[np.ndarray, float, float]:
    length = min(len(previous), len(following))
    previous = previous[-length:].astype(np.float32, copy=True)
    following = following[:length].astype(np.float32, copy=True)
    gain = np.full(length, MINIMUM_PREVIOUS_GAIN, dtype=np.float32)
    ramp_frames = min(length, max(1, round(rate * GAIN_RAMP_SECONDS)))
    gain[-ramp_frames:] = np.linspace(MINIMUM_PREVIOUS_GAIN, 0.0, ramp_frames, dtype=np.float32)
    mixed = following + previous * gain[:, None]
    limited, boundary_gain = limit_with_gain(mixed.astype(np.float32), rate)
    return limited, MINIMUM_PREVIOUS_GAIN, boundary_gain


def limit(samples: np.ndarray, rate: int) -> np.ndarray:
    return limit_with_gain(samples, rate)[0]


def limit_with_gain(samples: np.ndarray, rate: int) -> tuple[np.ndarray, float]:
    result = samples.astype(np.float32, copy=True)
    frames = len(result)
    lookahead = max(1, round(rate * LIMITER_LOOKAHEAD_SECONDS))
    release = np.float32(np.exp(-4.6051702 / (rate * LIMITER_RELEASE_SECONDS)))
    peaks = np.empty(frames, dtype=np.float32)
    for frame in range(frames):
        peak = np.float32(0)
        for channel in range(result.shape[1]):
            first = np.float32(result[frame, channel])
            peak = max(peak, abs(first))
            if frame + 1 < frames:
                second = np.float32(result[frame + 1, channel])
                for quarter in range(1, 4):
                    interpolated = np.float32(first + np.float32(second - first) * np.float32(quarter / 4))
                    peak = max(peak, abs(interpolated))
        peaks[frame] = peak
    desired = np.ones(frames, dtype=np.float32)
    for frame in range(frames):
        desired[frame] = np.float32(min(1.0, TRUE_PEAK_LIMIT / max(float(peaks[frame]), 1e-12)))
    attack_step = np.float32((1 - TRUE_PEAK_LIMIT / 2) / lookahead)
    for frame in range(frames - 2, -1, -1):
        desired[frame] = min(desired[frame], np.float32(desired[frame + 1] + attack_step))
    gain = np.float32(1.0)
    for frame in range(frames):
        required = desired[frame]
        gain = required if required < gain else np.float32(required + np.float32(gain - required) * release)
        result[frame] *= gain
    peak = true_peak(result)
    correction = min(1.0, TRUE_PEAK_LIMIT / max(peak, 1e-12))
    result *= correction
    return result, float(gain * correction)


def render(previous: np.ndarray, following: np.ndarray, rate: int, overlap_frames: int | None = None) -> tuple[np.ndarray, float, float, int, int]:
    length = min(len(previous), len(following), overlap_frames if overlap_frames is not None else max(len(previous), len(following)))
    pre_roll_frames = min(len(previous) - length, round(rate * PRE_ROLL_SECONDS))
    post_roll_frames = min(len(following) - length, round(rate * LIMITER_RELEASE_SECONDS))
    pre_roll = previous[len(previous) - length - pre_roll_frames:len(previous) - length].astype(np.float32, copy=True)
    if pre_roll_frames:
        pre_roll *= np.linspace(1.0, MINIMUM_PREVIOUS_GAIN, pre_roll_frames, dtype=np.float32)[:, None]
    tail = previous[-length:].astype(np.float32, copy=True)
    following_start = following[:length].astype(np.float32, copy=True)
    gain = np.full(length, MINIMUM_PREVIOUS_GAIN, dtype=np.float32)
    exit_frames = min(length, max(1, round(rate * GAIN_RAMP_SECONDS)))
    gain[-exit_frames:] = np.linspace(MINIMUM_PREVIOUS_GAIN, 0.0, exit_frames, dtype=np.float32)
    post_roll = following[length:length + post_roll_frames].astype(np.float32, copy=True)
    limited, boundary_gain = limit_with_gain(
        np.concatenate((pre_roll, following_start + tail * gain[:, None], post_roll)), rate,
    )
    return limited, MINIMUM_PREVIOUS_GAIN, boundary_gain, pre_roll_frames, post_roll_frames


def write_pcm16(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = np.round(np.clip(samples, -1, 32767 / 32768) * 32768).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setparams((samples.shape[1], 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(pcm.tobytes())

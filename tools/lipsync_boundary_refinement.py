"""Bounded waveform-based timing refinement for offline CTC LAB review."""
import numpy as np
from scipy import signal

TICKS = 10_000_000
VOWELS = frozenset(("a", "i", "u", "e", "o"))


def waveform_changes(audio, rate):
    """5ms feature timestamps are window centers, with a symmetric 25ms window."""
    samples = signal.resample_poly(audio, 16000, rate)
    hop, width = 80, 400
    padded = np.pad(samples, (width // 2, width // 2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, width)[::hop]
    rms = np.sqrt(np.mean(frames ** 2, axis=1))
    spectrum = np.abs(np.fft.rfft(frames * np.hanning(width), axis=1))
    band = spectrum[:, 5:101]  # 200–4000 Hz; avoid DC and ultrasonic noise
    normalized = band / np.maximum(np.linalg.norm(band, axis=1, keepdims=True), 1e-12)
    changes = np.zeros(len(frames))
    changes[1:] = np.sqrt(np.sum(np.diff(normalized, axis=0) ** 2, axis=1))
    # Difference between frames is located halfway between their centers.
    times = np.maximum(0, np.arange(len(frames)) * 0.005 - 0.0025)
    return times, changes, rms


def refine_boundaries(rows, events, times, changes, rms):
    """Move vowel boundaries <=40ms only with CTC and a stronger WAV change.

    Keep the label sequence and every quiet/closure boundary unchanged. A 60ms
    floor protects both neighboring vowels; existing shorter vowels are left alone.
    CTC confidence and acoustic thresholds are experimental, not calibrated accuracy.
    """
    result, decisions = list(rows), []
    for index in range(1, len(result)):
        left, right = result[index - 1], result[index]
        if left[2] not in VOWELS or right[2] not in VOWELS:
            continue
        boundary = left[1] / TICKS
        candidates = [event for event in events if event["phone"].lower() == right[2]
                      and event["confidence"] >= 0.95 and abs(event["time"] - boundary) <= 0.1]
        if not candidates:
            continue
        anchor = min(candidates, key=lambda event: abs(event["time"] - boundary))["time"] - 0.01
        minimum = max(boundary - 0.04, left[0] / TICKS + 0.06)
        maximum = min(boundary + 0.04, right[1] / TICKS - 0.06)
        if minimum >= maximum:
            continue
        choices = np.flatnonzero((times >= minimum) & (times <= maximum) & (rms >= 0.009))
        if not len(choices):
            continue
        score = changes[choices] - 0.05 * np.abs(times[choices] - anchor) / 0.04
        best = choices[int(np.argmax(score))]
        original = int(np.argmin(np.abs(times - boundary)))
        if changes[best] < max(0.08, changes[original] * 1.25 + 0.02):
            continue
        proposed = round(times[best] * TICKS)
        if abs(proposed - left[1]) < 50_000:
            continue
        result[index - 1] = (left[0], proposed, left[2])
        result[index] = (proposed, right[1], right[2])
        decisions.append({"fromSeconds": boundary, "toSeconds": proposed / TICKS,
                          "left": left[2], "right": right[2], "ctcAnchorSeconds": anchor,
                          "waveformChangeBefore": float(changes[original]),
                          "waveformChangeAfter": float(changes[best])})
    return result, decisions

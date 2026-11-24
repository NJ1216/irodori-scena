"""Thin wrappers for validated native local-processing operations."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import scena_native


def render_overlap_wav(
    previous: Path,
    following: Path,
    seconds: float,
    output: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, float]:
    values = (previous, following, seconds, output)
    try:
        rendered = scena_native.render_overlap_wav(*values, should_cancel)
    except TypeError:
        # A development server may still have the preceding extension loaded.
        rendered = scena_native.render_overlap_wav(*values)
    duration, pre_roll, post_roll, previous_gain, following_gain = rendered
    return {
        "durationSeconds": float(duration),
        "preRollSeconds": float(pre_roll),
        "postRollSeconds": float(post_roll),
        "previousGain": float(previous_gain),
        "followingGain": float(following_gain),
    }


def overlap_following_gain(path: Path, seconds: float) -> float:
    return float(scena_native.overlap_following_gain(path, seconds))


def mix_pcm_members_wav(members: list[tuple[Path, float]], output: Path) -> float:
    return float(scena_native.mix_pcm_members_wav(members, output))


def render_timeline_wav(
    members: list[tuple[Path, int, int]],
    start: int,
    end: int,
    rate: int,
    channels: int,
    output: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> None:
    """Render one bounded interval; never fall back to an adjacent two-voice mix."""
    scena_native.render_timeline_wav(members, start, end, rate, channels, output, should_cancel)

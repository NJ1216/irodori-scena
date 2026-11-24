from __future__ import annotations

import hashlib
import json
import struct
import threading
import time
import wave
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException

from server.modules.timeline import unit_starts as effective_unit_starts
from server.registry import deps
from server.native_processing import render_overlap_wav


OVERLAP_ALGORITHM_VERSION = "adjacent-overlap-v6"
TRUE_PEAK_LIMIT = 10 ** (-1 / 20)
GAIN_RAMP_SECONDS = 0.05
EXIT_RAMP_SECONDS = 0.01
LIMITER_LOOKAHEAD_SECONDS = 0.005
LIMITER_RELEASE_SECONDS = 0.06
MINIMUM_PREVIOUS_GAIN = 10 ** (-3 / 20)
_MIX_LOCKS: dict[str, threading.Lock] = {}
_MIX_LOCKS_GUARD = threading.Lock()
_PLAN_CACHE: dict[str, dict[str, dict[str, Any]]] = {}
_PLAN_CACHE_LOCK = threading.Lock()


def _mix_lock(signature: str) -> threading.Lock:
    with _MIX_LOCKS_GUARD:
        return _MIX_LOCKS.setdefault(signature, threading.Lock())




def overlap_signature(previous: dict[str, Any], following: dict[str, Any], effective_gap: float) -> str:
    payload = {
        "algorithm": OVERLAP_ALGORITHM_VERSION,
        "previous": previous,
        "following": following,
        "effectiveGap": round(effective_gap, 6),
        "truePeakLimit": TRUE_PEAK_LIMIT,
        "preRollSeconds": GAIN_RAMP_SECONDS,
        "exitRampSeconds": EXIT_RAMP_SECONDS,
        "limiterLookaheadSeconds": LIMITER_LOOKAHEAD_SECONDS,
        "limiterReleaseSeconds": LIMITER_RELEASE_SECONDS,
        "minimumPreviousGain": MINIMUM_PREVIOUS_GAIN,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def render_overlap(
    previous_path: Path,
    following_path: Path,
    seconds: float,
    output: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, float]:
    return render_overlap_wav(previous_path, following_path, seconds, output, should_cancel)


def _decode_pcm_window(path: Path, start: int, count: int) -> list[tuple[float, ...]]:
    """Decode at most `count` frames as float32-scaled samples, one tuple per frame."""
    with wave.open(str(path), "rb") as reader:
        channels, width = reader.getnchannels(), reader.getsampwidth()
        reader.setpos(max(0, min(start, reader.getnframes())))
        raw = reader.readframes(max(0, count))
    if width == 1:
        values = [(byte - 128) / 128 for byte in raw]
    elif width in (2, 3, 4):
        scale = float(1 << (8 * width - 1))
        values = [int.from_bytes(raw[index : index + width], "little", signed=True) / scale
                  for index in range(0, len(raw) - width + 1, width)]
    else:
        raise ValueError(f"Unsupported PCM sample width: {width}")
    samples = [struct.unpack("<f", struct.pack("<f", value))[0] for value in values]
    return [tuple(samples[index : index + channels]) for index in range(0, len(samples) - channels + 1, channels)]


def _dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return sum(a * b for a, b in zip(left, right))


def cached_overlap_boundary_gain(
    output: Path, following_path: Path, overlap_frames: int, post_roll_frames: int
) -> float:
    window = min(post_roll_frames + 1, 32)
    with wave.open(str(output), "rb") as reader:
        mixed_start = max(0, reader.getnframes() - window)
    following_start = max(0, overlap_frames + post_roll_frames - window)
    mixed = _decode_pcm_window(output, mixed_start, window)
    following = _decode_pcm_window(following_path, following_start, window)
    for offset in range(1, min(post_roll_frames + 1, 32) + 1):
        if offset > len(following) or offset > len(mixed):
            continue
        source = following[-offset]
        denominator = _dot(source, source)
        if denominator > 1e-8:
            return max(0.0, min(1.0, _dot(mixed[-offset], source) / denominator))
    return 1.0


def _unit_signature(cue: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    if not cue or any(deps.selected_take_record(line) is None for line in cue):
        raise ValueError("A selected take is required for every cue member.")
    paths = [deps.take_audio_path(deps.selected_take_record(line) or {}) for line in cue]
    decoded = []
    for path in paths:
        with wave.open(str(path), "rb") as reader:
            decoded.append((reader.getnframes(), reader.getframerate(), reader.getnchannels()))
    if len({(rate, channels) for _frames, rate, channels in decoded}) != 1:
        raise ValueError("Cue members have incompatible audio formats.")
    rate = decoded[0][1]
    duration = (
        max(
            round(deps.normalize_start_offset(line.get("startOffsetSeconds")) * rate) + decoded[index][0]
            for index, line in enumerate(cue)
        )
        / rate
        if len(cue) > 1
        else decoded[0][0] / rate
    )
    return {
        "duration": duration,
        "signature": deps.cue_mix_signature(cue) if len(cue) > 1 else deps.audio_file_identity(paths[0]),
        "lineIds": [str(line.get("id", "")) for line in cue],
        "takes": [str((deps.selected_take_record(line) or {}).get("id", "")) for line in cue],
        "hashMs": (time.perf_counter() - started) * 1000,
    }


def _overlap_plan_key(project: dict[str, Any]) -> str:
    payload = json.dumps(
        {"projectFile": str(deps.PROJECT_FILE.resolve()), "project": project},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _describe_segment(units: list[dict[str, Any]], default_gap: float) -> dict[str, dict[str, Any]]:
    durations = [float(unit["duration"]) for unit in units]
    gaps: list[float] = []
    for unit in units[:-1]:
        value = deps._strict_float(unit["cue"][0].get("gapSeconds"))
        gaps.append(max(-9999.0, min(9999.0, value if value is not None else default_gap)))
    _starts, effective = effective_unit_starts(durations, gaps)

    boundaries: dict[str, dict[str, Any]] = {}
    for index, effective_gap in enumerate(effective):
        previous = units[index]
        following = units[index + 1]
        if effective_gap >= 0:
            continue
        # Compatibility endpoint cannot represent reversed onsets or 3+ voices.
        left, right = _starts[index + 1], _starts[index] + durations[index]
        others = [j for j in range(len(units)) if j not in (index, index + 1)]
        if left < _starts[index] or any(_starts[j] < right and _starts[j] + durations[j] > left for j in others):
            continue
        previous_record = {
            "lineIds": previous["lineIds"],
            "takeIds": previous["takes"],
            "mix": previous["signature"],
            "duration": previous["duration"],
        }
        following_record = {
            "lineIds": following["lineIds"],
            "takeIds": following["takes"],
            "mix": following["signature"],
            "duration": following["duration"],
        }
        line_id = str(previous["cue"][0].get("id", ""))
        if line_id:
            boundaries[line_id] = {
                "leadingLineId": line_id,
                "signature": overlap_signature(previous_record, following_record, effective_gap),
                "effectiveGapSeconds": effective_gap,
                "previous": previous,
                "following": following,
                "hashMs": float(previous.get("hashMs", 0.0)) + float(following.get("hashMs", 0.0)),
            }
    return boundaries


def _build_overlap_boundaries(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configured_gap = deps._strict_float(project.get("settings", {}).get("lineGap"))
    default_gap = configured_gap if configured_gap is not None else 0.7
    segment: list[dict[str, Any]] = []
    for scene in project.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        for cue in deps.cue_groups(scene.get("lines", [])):
            try:
                descriptor = _unit_signature(cue)
            except (OSError, EOFError, ValueError, RuntimeError, wave.Error, HTTPException):
                # Unknown durations can move any later negative boundary backwards.
                return {}
            segment.append({"scene": scene, "cue": cue, **descriptor})
    return _describe_segment(segment, default_gap)


def prepare_overlap_boundaries(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Describe every renderable negative boundary with one project-wide audio scan."""
    plan_key = _overlap_plan_key(project)
    with _PLAN_CACHE_LOCK:
        cached = _PLAN_CACHE.get(plan_key)
        if cached is not None:
            return cached
        boundaries = _build_overlap_boundaries(project)
        _PLAN_CACHE.clear()
        _PLAN_CACHE[plan_key] = boundaries
        return boundaries


def _prepared_unit_audio(unit: dict[str, Any]) -> dict[str, Any]:
    cue = unit["cue"]
    if len(cue) > 1:
        mixed = deps.render_cue_mix(unit["scene"], str(cue[0].get("id", "")))
        if mixed["signature"] != unit["signature"]:
            raise RuntimeError("The cue changed after overlap preparation was planned.")
        path = deps.MEDIA_ROOT / str(mixed["audioUrl"]).removeprefix("/media/")
    else:
        path = deps.take_audio_path(deps.selected_take_record(cue[0]) or {})
    return {**unit, "path": path}


def render_prepared_overlap(
    boundary: dict[str, Any],
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Render a boundary without rereading the project or rescanning timeline headers."""
    previous = _prepared_unit_audio(boundary["previous"])
    following = _prepared_unit_audio(boundary["following"])
    effective_gap = float(boundary["effectiveGapSeconds"])
    signature = str(boundary["signature"])
    output = deps.MEDIA_ROOT / "cache" / "overlap-mixes" / f"{signature}.wav"
    rendered: dict[str, float] | None = None
    cache_started = time.perf_counter()
    native_ms = 0.0
    with _mix_lock(signature):
        cache_hit = output.is_file()
        cache_lookup_ms = (time.perf_counter() - cache_started) * 1000
        if cache_hit:
            with wave.open(str(output), "rb") as reader:
                cached_seconds = reader.getnframes() / reader.getframerate()
                rate = reader.getframerate()
            duration = min(-effective_gap, previous["duration"], following["duration"])
            pre_roll = min(GAIN_RAMP_SECONDS, max(0.0, previous["duration"] - duration))
            post_roll = max(0.0, cached_seconds - duration - pre_roll)
            following_gain = cached_overlap_boundary_gain(
                output, following["path"], round(duration * rate), round(post_roll * rate)
            )
        else:
            if should_cancel and should_cancel():
                raise InterruptedError("Overlap preparation was interrupted.")
            native_started = time.perf_counter()
            rendered = render_overlap(previous["path"], following["path"], -effective_gap, output, should_cancel)
            native_ms = (time.perf_counter() - native_started) * 1000
            if should_cancel and should_cancel():
                output.unlink(missing_ok=True)
                raise InterruptedError("Overlap preparation was interrupted.")
            duration = rendered["durationSeconds"]
            pre_roll = rendered["preRollSeconds"]
            post_roll = rendered["postRollSeconds"]
            following_gain = rendered["followingGain"]
        deps.persist_derived_cache(output)
    return {
        "audioUrl": deps.media_url(output),
        "durationSeconds": round(duration, 6),
        "preRollSeconds": round(pre_roll, 6),
        "postRollSeconds": round(post_roll, 6),
        "followingGain": round(following_gain, 8),
        "effectiveGapSeconds": round(effective_gap, 6),
        "signature": signature,
        "leadingLineIds": previous["lineIds"],
        "followingLineIds": following["lineIds"],
        "diagnostics": {
            "snapshotMs": 0.0,
            "hashMs": round(float(boundary.get("hashMs", 0.0)), 3),
            "cacheHit": cache_hit,
            "cacheLookupMs": round(cache_lookup_ms, 3),
            "nativeMs": round(native_ms, 3),
        },
    }


def overlap_cache_signatures(project: dict[str, Any]) -> set[str]:
    """Return cache keys still reproducible from the project's selected takes."""
    try:
        boundaries = prepare_overlap_boundaries(project)
    except (OSError, EOFError, ValueError, RuntimeError, wave.Error, HTTPException):
        return set()
    return {str(boundary["signature"]) for boundary in boundaries.values()}


def render_adjacent_overlap(
    project: dict[str, Any],
    leading_line_id: str,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    prepared = prepare_overlap_boundaries(project)
    if leading_line_id in prepared:
        return render_prepared_overlap(prepared[leading_line_id], should_cancel)
    raise HTTPException(status_code=422, detail="指定された境界は隣接2行mixでは処理できません。")


deps.register(
    __name__,
    [
        "EXIT_RAMP_SECONDS",
        "GAIN_RAMP_SECONDS",
        "LIMITER_LOOKAHEAD_SECONDS",
        "LIMITER_RELEASE_SECONDS",
        "MINIMUM_PREVIOUS_GAIN",
        "OVERLAP_ALGORITHM_VERSION",
        "TRUE_PEAK_LIMIT",
        "cached_overlap_boundary_gain",
        "effective_unit_starts",
        "overlap_cache_signatures",
        "overlap_signature",
        "prepare_overlap_boundaries",
        "render_adjacent_overlap",
        "render_overlap",
        "render_prepared_overlap",
    ],
)

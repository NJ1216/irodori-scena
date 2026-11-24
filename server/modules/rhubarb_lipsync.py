from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from server import subprocess_boundary as subprocess
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Callable

from server.registry import deps
from server.modules.japanese_lipsync_addon import refine_with_addon


TICKS_PER_SECOND = 10_000_000
SHAPE_TO_LAB = {"A": "N", "B": "i", "C": "e", "D": "a", "E": "o", "F": "u", "X": "pau"}
_CACHE_SESSION_ID = uuid.uuid4().hex
_CACHE_LOCKS: dict[str, threading.Lock] = {}
_CACHE_LOCKS_GUARD = threading.Lock()


def _session_cache_root() -> Path:
    return deps.RHUBARB_CACHE_ROOT / _CACHE_SESSION_ID


def _remove_previous_cache_entries(root: Path, current: Path) -> None:
    try:
        entries = list(root.iterdir())
    except OSError:
        return
    for item in entries:
        if item == current:
            continue
        try:
            if item.is_symlink() or item.is_file():
                item.unlink(missing_ok=True)
            else:
                shutil.rmtree(item, ignore_errors=True)
        except OSError:
            continue


@deps.app.on_event("startup")
def begin_rhubarb_cache_session() -> None:
    root = deps.RHUBARB_CACHE_ROOT
    current = _session_cache_root()
    current.mkdir(parents=True, exist_ok=True)
    threading.Thread(
        target=_remove_previous_cache_entries,
        args=(root, current),
        name="scena-rhubarb-cache-cleanup",
        daemon=True,
    ).start()


def _wav_fingerprint(path: Path) -> tuple[str, float]:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    with wave.open(str(path), "rb") as reader:
        duration = reader.getnframes() / reader.getframerate()
    return digest.hexdigest(), duration


def rhubarb_parallelism(task_count: int) -> tuple[int, int]:
    """Split logical CPUs across a small number of independent WAV jobs."""
    logical_cpus = max(1, os.cpu_count() or 1)
    worker_limit = max(1, min(4, logical_cpus // 2))
    workers = max(1, min(task_count, worker_limit))
    return workers, max(1, logical_cpus // workers)


def _cache_lock(key: str, should_cancel: Callable[[], bool]) -> threading.Lock:
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.setdefault(key, threading.Lock())
    while not lock.acquire(timeout=0.1):
        if should_cancel():
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
    return lock


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()


def _run_rhubarb(command: list[str], cwd: Path, timeout: float, should_cancel: Callable[[], bool]) -> None:
    process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    while True:
        if should_cancel():
            _stop_process(process)
            raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _stop_process(process)
            raise RuntimeError("Rhubarbの解析がタイムアウトしました。")
        try:
            stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
    if process.returncode != 0:
        diagnostic = (stderr or stdout).strip().splitlines()[-1:] or ["詳細なし"]
        raise RuntimeError(f"Rhubarbの解析に失敗しました: {diagnostic[0]}")


def _parse_cues(payload: dict[str, Any]) -> list[tuple[float, float, str]]:
    raw = payload.get("mouthCues")
    if not isinstance(raw, list):
        raise ValueError("Rhubarb JSONにmouthCuesがありません。")
    cues, previous_end = [], 0.0
    for cue in raw:
        if not isinstance(cue, dict):
            raise ValueError("Rhubarb JSONの口形が不正です。")
        start, end, shape = cue.get("start"), cue.get("end"), cue.get("value")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or shape not in SHAPE_TO_LAB:
            raise ValueError("Rhubarb JSONの時刻または口形が不正です。")
        start, end = float(start), float(end)
        if not math.isfinite(start) or not math.isfinite(end) or start < previous_end or end <= start:
            raise ValueError("Rhubarb JSONの口形区間が順序どおりではありません。")
        cues.append((start, end, str(shape)))
        previous_end = end
    return cues


def _lab_rows(cues: list[tuple[float, float, str]], duration: float) -> list[tuple[int, int, str]]:
    duration_ticks = round(duration * TICKS_PER_SECOND)
    if duration_ticks <= 0:
        raise ValueError("WAVの長さが不正です。")
    rows: list[tuple[int, int, str]] = []
    cursor = 0
    for start, end, shape in cues:
        start_tick = min(duration_ticks, max(cursor, round(start * TICKS_PER_SECOND)))
        end_tick = min(duration_ticks, max(start_tick, round(end * TICKS_PER_SECOND)))
        if start_tick > cursor:
            rows.append((cursor, start_tick, "pau"))
        if end_tick > start_tick:
            rows.append((start_tick, end_tick, SHAPE_TO_LAB[shape]))
            cursor = end_tick
        if cursor >= duration_ticks:
            break
    if cursor < duration_ticks:
        rows.append((cursor, duration_ticks, "pau"))
    merged: list[tuple[int, int, str]] = []
    for start, end, label in rows:
        if merged and merged[-1][2] == label:
            merged[-1] = (merged[-1][0], end, label)
        else:
            merged.append((start, end, label))
    if not merged or merged[0][0] != 0 or merged[-1][1] != duration_ticks:
        raise ValueError("連続したLABを生成できませんでした。")
    return merged


def generate_rhubarb_lab(
    wav_path: Path, should_cancel: Callable[[], bool], thread_count: int | None = None, *, addon_session=None,
) -> str:
    wav_path = wav_path.resolve()
    executable = deps.rhubarb_executable()
    wav_sha, duration = _wav_fingerprint(wav_path)
    release_id = str(deps.rhubarb_status()["releaseId"])
    cache = _session_cache_root() / release_id / f"{wav_sha}.json"
    lock = _cache_lock(f"{release_id}:{wav_sha}", should_cancel)
    try:
        payload: dict[str, Any] | None = None
        if cache.is_file():
            try:
                cached = json.loads(cache.read_text())
                if cached.get("wavSha256") == wav_sha and cached.get("releaseId") == release_id:
                    payload = {"mouthCues": cached.get("mouthCues")}
                    _parse_cues(payload)
            except (OSError, ValueError, json.JSONDecodeError):
                payload = None
        if payload is None:
            if should_cancel():
                raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
            timeout = min(600.0, max(30.0, duration * 4))
            with tempfile.TemporaryDirectory(prefix="scena-rhubarb-") as temporary:
                output = Path(temporary) / "result.json"
                command = [str(executable), "-f", "json", "-r", "phonetic", "--extendedShapes", "X"]
                if thread_count is not None:
                    command.extend(("--threads", str(max(1, thread_count))))
                command.extend(("--machineReadable", "-o", str(output), str(wav_path)))
                _run_rhubarb(command, executable.parent, timeout, should_cancel)
                payload = json.loads(output.read_text())
            _parse_cues(payload)
            cache.parent.mkdir(parents=True, exist_ok=True)
            temporary_cache = cache.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
            temporary_cache.write_text(json.dumps({"schemaVersion": 1, "releaseId": release_id, "wavSha256": wav_sha, "durationSeconds": duration, "mouthCues": payload["mouthCues"]}, ensure_ascii=False))
            os.replace(temporary_cache, cache)
    finally:
        lock.release()
    rows = _lab_rows(_parse_cues(payload), duration)
    rows = refine_with_addon(wav_path, rows, wav_sha, duration, executable, release_id,
                             _session_cache_root(), should_cancel,
                             addon_session.run if addon_session is not None else _run_rhubarb, _cache_lock,
                             loaded_addon=getattr(addon_session, 'loaded_addon', None))
    return "".join(f"{start} {end} {label}\n" for start, end, label in rows)


deps.register(__name__, ["begin_rhubarb_cache_session", "generate_rhubarb_lab", "rhubarb_parallelism"])

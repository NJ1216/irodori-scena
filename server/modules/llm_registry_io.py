"""File access for llm-registry.json that never waits for a model load.

The file lock guards only a read and the atomic replace: Windows opens files without FILE_SHARE_DELETE, so
replacing the registry while another thread reads it would fail. Saves that are merely convenient (a
migration or an invalidation found while reading) run only when the runtime lock is free; a Windows TTS
load holds that lock for its whole duration, and the next read repeats the work.
"""
from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

FILE_LOCK = threading.Lock()


def read_text(path: Path) -> str:
    with FILE_LOCK:
        return path.read_text(encoding="utf-8")


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with FILE_LOCK:
            temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def file_version(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def save_unless_changed(path: Path, version, registry: dict[str, Any], write: Callable, invalidate: Callable,
                        reread: Callable[[], dict[str, Any]]) -> None:
    """Save an invalidated view, or redo the invalidation on a registry another writer changed meanwhile."""
    if file_version(path) != version:
        registry = reread()
        if not invalidate(registry):
            return
    write(registry)


def when_free(lock: threading.RLock, save: Callable[[], Any], skipped: Any = None) -> Any:
    """Run save under the runtime lock only if it is free now; otherwise return skipped."""
    if not lock.acquire(blocking=False):
        return skipped
    try:
        return save()
    finally:
        lock.release()

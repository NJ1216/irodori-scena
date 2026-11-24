"""WAV content identity, including same-size/same-mtime replacement detection."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path

_CACHE: OrderedDict[tuple[str, int, int, int, int], str] = OrderedDict()
_LOCK = threading.Lock()


def _key(path: Path) -> tuple[str, int, int, int, int]:
    stat = path.stat()
    return str(path.resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


def audio_identity(path: Path) -> str:
    key = _key(path)
    with _LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    if _key(path) != key:
        raise OSError("Timeline input changed during content hashing.")
    value = digest.hexdigest()
    with _LOCK:
        _CACHE[key] = value
        while len(_CACHE) > 1024:
            _CACHE.popitem(last=False)
    return value

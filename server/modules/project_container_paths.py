from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Iterator
from fastapi import HTTPException

EXCLUDED_PARTS = {"exports", "candidates", ".cleanup", ".rollback"}
SYNC_INDEX_NAME = ".scena-sync-index.json"
EXCLUDED_NAMES = {".DS_Store", ".irodori-synthesis.lock", SYNC_INDEX_NAME}
TEMP_MARKERS = (".partial", ".staging-", ".previous-", ".tmp")
ALREADY_COMPRESSED = {".png", ".jpg", ".jpeg", ".webp"}
DERIVED_AUDIO_PREFIXES = {
    ("media", "cache", "cue-mixes"),
    ("media", "cache", "overlap-mixes"),
    ("media", "cache", "timeline-v1"),
}

def _safe_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or "\\" in value or any(part in {"", ".", ".."} for part in path.parts):
        raise HTTPException(status_code=422, detail=f"コンテナ内のパスが不正です: {value!r}")
    return path


def _included(relative: PurePosixPath) -> bool:
    if relative.name in EXCLUDED_NAMES or any(marker in relative.name for marker in TEMP_MARKERS):
        return False
    parts = relative.parts
    if parts[:3] == ("media", "cache", "timeline-v1"):
        return False
    return not (len(parts) >= 2 and parts[0] == "media" and parts[1] in EXCLUDED_PARTS)


def _derived_audio(relative: PurePosixPath | str) -> bool:
    parts = PurePosixPath(relative).parts
    return any(parts[: len(prefix)] == prefix for prefix in DERIVED_AUDIO_PREFIXES)


def _iter_paths(root: Path, *, include_derived_audio: bool = True, root_entries: frozenset[str] | None = None) -> Iterator[tuple[PurePosixPath, Path, str]]:
    for directory, names, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        if parent == root and root_entries is not None:
            names[:] = [name for name in names if name in root_entries]
            files = [name for name in files if name in root_entries]
        names[:] = sorted(
            name for name in names if _included(PurePosixPath((parent / name).relative_to(root).as_posix()))
        )
        relative_dir = PurePosixPath(parent.relative_to(root).as_posix())
        if relative_dir != PurePosixPath(".") and _included(relative_dir):
            if include_derived_audio or not _derived_audio(relative_dir):
                yield relative_dir, parent, "directory"
        for name in sorted(files):
            path = parent / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if _included(relative) and (include_derived_audio or not _derived_audio(relative)):
                if path.is_symlink():
                    raise HTTPException(status_code=422, detail=f"シンボリックリンクは格納できません: {relative}")
                yield relative, path, "file"

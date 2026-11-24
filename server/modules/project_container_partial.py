"""Bounded updates of project metadata and selected Take subtrees."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path, PurePosixPath

from fastapi import HTTPException


def _sync_file(pc, connection: sqlite3.Connection, source: Path, relative: str, index) -> None:
    compressed, size, digest = pc._compressed_copy(source)
    try:
        use_compression = source.suffix.lower() not in pc.ALREADY_COMPRESSED and compressed.stat().st_size < size
        pc._write_blob(connection, relative, compressed if use_compression else source, "zstd" if use_compression else "none", size, digest)
        if index is not None:
            index[relative] = pc._file_metadata(source, digest)
    finally:
        compressed.unlink(missing_ok=True)


def _replace_target(pc, connection: sqlite3.Connection, root: Path, relative: PurePosixPath, index):
    prefix = relative.as_posix()
    connection.execute("DELETE FROM entries WHERE path=? OR path GLOB ?", (prefix, f"{prefix}/*"))
    if index is not None:
        index = {name: value for name, value in index.items() if name != prefix and not name.startswith(f"{prefix}/")}
    target = root / Path(*relative.parts)
    if not target.exists():
        return index
    empty_digest = hashlib.sha256(b"").hexdigest()
    connection.execute("INSERT INTO entries VALUES (?, 'directory', 'none', 0, ?, X'')", (prefix, empty_digest))
    for child in sorted(target.rglob("*")):
        name = child.relative_to(root).as_posix()
        if child.is_dir():
            connection.execute("INSERT INTO entries VALUES (?, 'directory', 'none', 0, ?, X'')", (name, empty_digest))
        elif child.is_file():
            _sync_file(pc, connection, child, name, index)
    return index


def sync_project_and_media_targets(container: Path, root: Path, media_targets: list[str]) -> None:
    """Update project.json and explicit Take subtrees without inspecting siblings."""
    from server.modules import project_container as pc

    targets = [pc._safe_path(f"media/{value}") for value in dict.fromkeys(media_targets)]
    if any(target.parts[:2] not in {("media", "takes"), ("media", "characters")} for target in targets):
        raise HTTPException(status_code=422, detail="履歴の媒体対象が不正です。")
    project = root / "project.json"
    if not project.is_file() or not container.is_file():
        raise HTTPException(status_code=409, detail="プロジェクトの部分保存を開始できません。")
    with pc._SYNC_LOCK:
        cached = pc._load_sync_index(container, root)
        index = dict(cached) if cached is not None else None
        stage = pc._stage_legacy(container)
        connection = pc._connect(stage or container)
        try:
            app_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if app_id != pc.APPLICATION_ID or version != pc.FORMAT_VERSION:
                raise HTTPException(status_code=409, detail="プロジェクトの部分保存先が一致しません。")
            with connection:
                _sync_file(pc, connection, project, "project.json", index)
                for target in targets:
                    index = _replace_target(pc, connection, root, target, index)
            connection.close()
            connection = None
            if stage is not None:
                pc._publish_stage(stage, container)
            with container.open("r+b") as stream:
                os.fsync(stream.fileno())
            if index is None:
                pc._index_path(root).unlink(missing_ok=True)
            else:
                pc._refresh_sync_index(container, root, index)
        finally:
            if connection is not None:
                connection.close()
            if stage is not None:
                stage.unlink(missing_ok=True)

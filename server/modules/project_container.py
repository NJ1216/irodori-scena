from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException

from server.file_lock import lock_exclusive, unlock
from server.modules import project_container_codec as codec
from server.registry import deps
from server.modules.project_container_paths import (  # noqa: F401
    EXCLUDED_PARTS, SYNC_INDEX_NAME, EXCLUDED_NAMES, TEMP_MARKERS, ALREADY_COMPRESSED, DERIVED_AUDIO_PREFIXES,
    _safe_path, _included, _derived_audio, _iter_paths,
)

APPLICATION_ID = 0x53434E41  # SCNA
FORMAT_VERSION = 2
CHUNK_SIZE = 1024 * 1024
MAX_ENTRY_SIZE = 16 * 1024**3

_lock_stream: BinaryIO | None = None
_locked_container: Path | None = None
_SYNC_LOCK = threading.RLock()


def container_signature(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def _index_path(root: Path) -> Path:
    return root / SYNC_INDEX_NAME


def _load_sync_index(container: Path, root: Path) -> dict[str, dict[str, object]] | None:
    try:
        payload = json.loads(_index_path(root).read_text(encoding="utf-8"))
        if payload.get("container") != str(container.resolve()) or tuple(
            payload.get("signature", ())
        ) != container_signature(container):
            return None
        entries = payload.get("entries")
        return entries if isinstance(entries, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _write_sync_index(container: Path, root: Path, entries: dict[str, dict[str, object]]) -> None:
    destination = _index_path(root)
    temporary = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    payload = {
        "version": 1,
        "container": str(container.resolve()),
        "signature": container_signature(container),
        "entries": entries,
    }
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def _refresh_sync_index(container: Path, root: Path, entries: dict[str, dict[str, object]]) -> None:
    try:
        _write_sync_index(container, root, entries)
    except OSError:
        _index_path(root).unlink(missing_ok=True)


def _file_metadata(path: Path, digest: str) -> dict[str, object]:
    stat = path.stat()
    return {"kind": "file", "size": stat.st_size, "mtimeNs": stat.st_mtime_ns, "inode": stat.st_ino, "sha256": digest}


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
    connection.row_factory = sqlite3.Row
    return connection


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version={FORMAT_VERSION}")
    connection.execute(
        "CREATE TABLE IF NOT EXISTS entries ("
        "path TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('file','directory')), "
        "compression TEXT NOT NULL CHECK(compression IN ('none','deflate','zstd')), "
        "original_size INTEGER NOT NULL CHECK(original_size >= 0), "
        "sha256 TEXT NOT NULL, data BLOB NOT NULL)"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS cache_provenance ("
        "path TEXT PRIMARY KEY, plan_id TEXT NOT NULL, start_frame INTEGER NOT NULL, "
        "end_frame INTEGER NOT NULL, targets TEXT NOT NULL)"
    )


def _validate_header(connection: sqlite3.Connection, *, deep: bool = True) -> None:
    """Check identity and version; ``deep`` adds a full integrity scan (opening, validation, backups).

    The scan reads the whole file, so write paths of an already validated container
    pass ``deep=False`` instead of paying it on every save.
    """
    app_id = int(connection.execute("PRAGMA application_id").fetchone()[0])
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if app_id != APPLICATION_ID:
        raise HTTPException(status_code=422, detail="irodori SCENAプロジェクトではありません。")
    if version not in (1, FORMAT_VERSION):
        raise HTTPException(status_code=422, detail=f"未対応の.scena形式バージョンです: {version}")
    if not deep:
        return
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise HTTPException(status_code=422, detail=f".scenaコンテナが破損しています: {integrity}")


def _compressed_copy(source: Path, *, level: int = 1) -> tuple[Path, int, str]:
    return codec.compressed_copy(__import__(__name__, fromlist=["."]), source, level=level)


def _plain_metadata(source: Path) -> tuple[int, str]:
    return codec.plain_metadata(__import__(__name__, fromlist=["."]), source)


def _write_blob(
    connection: sqlite3.Connection, relative: str, source: Path, compression: str, size: int, digest: str
) -> None:
    codec.write_blob(__import__(__name__, fromlist=["."]), connection, relative, source, compression, size, digest)


def _stage_legacy(container: Path) -> Path | None:
    return codec.stage_legacy(__import__(__name__, fromlist=["."]), container)


def container_requires_upgrade(container: Path) -> bool:
    with closing(_connect(container, readonly=True)) as connection:
        return codec.requires_upgrade(__import__(__name__, fromlist=["."]), connection)


def _publish_stage(stage: Path, container: Path) -> None:
    return codec.publish_stage(__import__(__name__, fromlist=["."]), stage, container)


def _sync_container(container: Path, root: Path, *, include_derived_audio: bool = True,
                    compact: bool = False, root_entries: frozenset[str] | None = None) -> None:
    """Transactionally mirror the eligible working tree into one .scena file."""
    if not (root / "project.json").is_file():
        raise HTTPException(status_code=422, detail="project.jsonがありません。")
    container.parent.mkdir(parents=True, exist_ok=True)
    # Explicit compaction rebuilds from the current working tree. For a legacy
    # container this drops its old encoding and recreatable derived cache
    # instead of copying those entries into the v2 database first.
    legacy_stage = _stage_legacy(container) if container.exists() and not compact else None
    rebuilding = compact or not container.exists() or legacy_stage is not None
    cached = None if rebuilding else _load_sync_index(container, root)
    target = container.with_name(f".{container.name}.staging-{os.getpid()}") if rebuilding else container
    if rebuilding and legacy_stage is None:
        target.unlink(missing_ok=True)
    connection = _connect(target)
    try:
        _create_schema(connection)
        seen: set[str] = set()
        next_index: dict[str, dict[str, object]] = {}
        with connection:
            for relative, source, kind in _iter_paths(
                root, include_derived_audio=include_derived_audio, root_entries=root_entries
            ):
                name = relative.as_posix()
                seen.add(name)
                if kind == "directory":
                    connection.execute(
                        "INSERT INTO entries VALUES (?, 'directory', 'none', 0, ?, X'') "
                        "ON CONFLICT(path) DO UPDATE SET kind='directory', compression='none', original_size=0, sha256=excluded.sha256, data=X''",
                        (name, hashlib.sha256(b"").hexdigest()),
                    )
                    continue
                stat = source.stat()
                indexed = cached.get(name) if cached is not None else None
                current = connection.execute(
                    "SELECT kind, compression, original_size, sha256 FROM entries WHERE path=?", (name,)
                ).fetchone()
                if (
                    isinstance(indexed, dict)
                    and indexed.get("kind") == "file"
                    and indexed.get("size") == stat.st_size
                    and indexed.get("mtimeNs") == stat.st_mtime_ns
                    and indexed.get("inode") == stat.st_ino
                    and current is not None
                    and current["kind"] == "file"
                    and current["original_size"] == stat.st_size
                    and current["sha256"] == indexed.get("sha256")
                ):
                    next_index[name] = indexed
                    continue
                compressed = None
                try:
                    if source.suffix.lower() in ALREADY_COMPRESSED:
                        size, digest = _plain_metadata(source)
                        use_compression = False
                    else:
                        compressed, size, digest = _compressed_copy(source)
                        use_compression = compressed.stat().st_size < size
                    stored = compressed if use_compression else source
                    compression = "zstd" if use_compression else "none"
                    if current and current["kind"] == "file" and current["original_size"] == size and current["sha256"] == digest:
                        next_index[name] = _file_metadata(source, digest)
                        continue
                    _write_blob(connection, name, stored, compression, size, digest)
                    next_index[name] = _file_metadata(source, digest)
                finally:
                    if compressed is not None:
                        compressed.unlink(missing_ok=True)
            if "project.json" not in seen:
                raise HTTPException(status_code=422, detail="project.jsonがありません。")
            for row in connection.execute("SELECT path FROM entries").fetchall():
                if row[0] not in seen and (include_derived_audio or not _derived_audio(row[0])):
                    connection.execute("DELETE FROM entries WHERE path=?", (row[0],))
        if rebuilding:
            connection.close()
            connection = None
            _publish_stage(target, container)
        else:
            connection.close()
            connection = None
            with container.open("r+b") as stream:
                os.fsync(stream.fileno())
        _refresh_sync_index(container, root, next_index)
    finally:
        if connection is not None:
            connection.close()
        if rebuilding:
            target.unlink(missing_ok=True)


def sync_container(container: Path, root: Path, *, include_derived_audio: bool = True,
                   compact: bool = False, root_entries: frozenset[str] | None = None) -> None:
    with _SYNC_LOCK:
        _sync_container(container, root, include_derived_audio=include_derived_audio,
                        compact=compact, root_entries=root_entries)


def sync_project_entry(container: Path, root: Path) -> bool:
    """Update only project.json when the last full-sync index proves container ownership."""
    with _SYNC_LOCK:
        if container.exists():
            with closing(_connect(container, readonly=True)) as existing:
                _validate_header(existing, deep=False)
                if existing.execute("PRAGMA user_version").fetchone()[0] == 1:
                    _sync_container(container, root, include_derived_audio=False)
                    return False
        cached = _load_sync_index(container, root) if container.exists() else None
        source = root / "project.json"
        if cached is None or "project.json" not in cached or not source.is_file():
            _sync_container(container, root, include_derived_audio=False)
            return False
        connection: sqlite3.Connection | None = None
        try:
            connection = _connect(container)
            _validate_header(connection, deep=False)
            compressed, size, digest = _compressed_copy(source)
            try:
                use_compression = compressed.stat().st_size < size
                stored = compressed if use_compression else source
                with connection:
                    _write_blob(connection, "project.json", stored, "zstd" if use_compression else "none", size, digest)
            finally:
                compressed.unlink(missing_ok=True)
            connection.close()
            connection = None
            with container.open("r+b") as stream:
                os.fsync(stream.fileno())
            next_index = dict(cached)
            next_index["project.json"] = _file_metadata(source, digest)
            _refresh_sync_index(container, root, next_index)
            return True
        except (OSError, sqlite3.DatabaseError, HTTPException):
            if connection is not None:
                connection.close()
            _sync_container(container, root, include_derived_audio=False)
            return False


def sync_project_and_media_targets(container: Path, root: Path, media_targets: list[str]) -> None:
    from server.modules.project_container_partial import sync_project_and_media_targets as sync_partial

    sync_partial(container, root, media_targets)


def validate_container(path: Path, *, staging: bool = False) -> list[sqlite3.Row]:
    if not path.is_absolute() or (not staging and path.suffix.lower() != ".scena") or not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=422, detail="通常ファイルの.scenaプロジェクトを指定してください。")
    try:
        with closing(_connect(path, readonly=True)) as connection:
            _validate_header(connection)
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            rows = connection.execute(
                "SELECT path, kind, compression, original_size, sha256, length(data) stored_size FROM entries ORDER BY path"
            ).fetchall()
    except sqlite3.DatabaseError as error:
        raise HTTPException(status_code=422, detail=f".scenaコンテナを読み取れません: {error}") from error
    names: set[str] = set()
    total = 0
    for row in rows:
        name = _safe_path(row["path"]).as_posix()
        digest = row["sha256"]
        if (
            name in names
            or not isinstance(row["original_size"], int)
            or not 0 <= row["original_size"] <= MAX_ENTRY_SIZE
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or row["compression"] not in (("none", "deflate") if version == 1 else ("none", "deflate", "zstd"))
        ):
            raise HTTPException(status_code=422, detail=".scenaコンテナのエントリ情報が不正です。")
        if row["kind"] == "directory" and (row["original_size"] or row["stored_size"]):
            raise HTTPException(status_code=422, detail="ディレクトリエントリが不正です。")
        total += row["original_size"]
        if total > MAX_ENTRY_SIZE:
            raise HTTPException(status_code=422, detail=".scenaコンテナの展開サイズが上限を超えています。")
        names.add(name)
    if "project.json" not in names:
        raise HTTPException(status_code=422, detail="project.jsonを含まない.scenaコンテナです。")
    return rows


def _extract_file(connection: sqlite3.Connection, row: sqlite3.Row, destination: Path) -> None:
    codec.extract_file(__import__(__name__, fromlist=["."]), connection, row, destination)


def extract_container(path: Path, destination: Path) -> None:
    rows = validate_container(path)
    required = sum(row["original_size"] for row in rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < required + 16 * 1024**2:
        raise HTTPException(status_code=507, detail="プロジェクトを開くための空き容量が不足しています。")
    staging = destination.with_name(f".{destination.name}.staging-{os.getpid()}")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        with closing(_connect(path, readonly=True)) as connection:
            for row in rows:
                target = staging.joinpath(*_safe_path(row["path"]).parts)
                if row["kind"] == "directory":
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    _extract_file(connection, row, target)
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def prepare_saved_workspace(container: Path, source: Path, destination: Path) -> None:
    """Copy only recorded entries, verifying copied bytes against the container index."""
    rows = validate_container(container)
    signature = container_signature(container)
    destination.mkdir(parents=True)
    index: dict[str, dict[str, object]] = {}
    for row in rows:
        relative = _safe_path(row["path"])
        target = destination.joinpath(*relative.parts)
        if row["kind"] == "directory":
            target.mkdir(parents=True, exist_ok=True)
            continue
        origin = source.joinpath(*relative.parts)
        if origin.is_symlink() or not origin.is_file():
            raise HTTPException(status_code=409, detail=f"保存中にファイルが変更されました: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with origin.open("rb") as input_stream, target.open("wb") as output:
            while chunk := input_stream.read(CHUNK_SIZE):
                size += len(chunk)
                if size > row["original_size"]:
                    raise HTTPException(status_code=409, detail=f"保存中にファイルが変更されました: {relative}")
                digest.update(chunk)
                output.write(chunk)
        if size != row["original_size"] or digest.hexdigest() != row["sha256"]:
            raise HTTPException(status_code=409, detail=f"保存中にファイルが変更されました: {relative}")
        index[row["path"]] = _file_metadata(target, digest.hexdigest())
    if container_signature(container) != signature:
        raise HTTPException(status_code=409, detail="保存中に.scenaプロジェクトが変更されました。")
    _write_sync_index(container, destination, index)


def working_root(path: Path) -> Path:
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
    return deps.DATA_ROOT / "project-workspaces" / digest


def acquire_container_lock(path: Path) -> None:
    global _lock_stream, _locked_container
    resolved = path.resolve()
    if _locked_container == resolved:
        return
    lock_path = deps.DATA_ROOT / "project-locks" / f"{hashlib.sha256(str(resolved).encode()).hexdigest()}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("a+b")
    try:
        lock_exclusive(stream)
    except BlockingIOError as error:
        stream.close()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_locked",
                "message": "このプロジェクトは別のSCENAで編集中です。別のSCENAを閉じてから、もう一度開いてください。",
            },
        ) from error
    release_container_lock()
    _lock_stream, _locked_container = stream, resolved


def release_container_lock() -> None:
    global _lock_stream, _locked_container
    if _lock_stream is not None:
        unlock(_lock_stream)
        _lock_stream.close()
    _lock_stream = None
    _locked_container = None


def active_container_path() -> Path | None:
    return _locked_container


def persist_active_container() -> None:
    if deps.ACTIVE_PROJECT_PATH is not None:
        sync_container(deps.ACTIVE_PROJECT_PATH, deps.ACTIVE_PROJECT_ROOT)


deps.register(
    __name__,
    [
        "acquire_container_lock",
        "active_container_path",
        "container_signature",
        "container_requires_upgrade",
        "extract_container",
        "persist_active_container",
        "prepare_saved_workspace",
        "sync_project_and_media_targets",
        "release_container_lock",
        "sync_container",
        "sync_project_entry",
        "validate_container",
        "working_root",
    ],
)

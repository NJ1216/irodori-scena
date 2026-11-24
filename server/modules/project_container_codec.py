"""Compression and legacy migration for .scena entries."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import zlib
from contextlib import closing
from pathlib import Path

import zstandard as zstd
from fastapi import HTTPException


def compressed_copy(pc, source: Path, *, level: int = 1) -> tuple[Path, int, str]:
    digest = hashlib.sha256()
    original_size = 0
    fd, raw_temp = tempfile.mkstemp(prefix="scena-entry-", suffix=".zstd")
    temp = Path(raw_temp)
    compressor = zstd.ZstdCompressor(level=level).compressobj()
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
            while chunk := stream.read(pc.CHUNK_SIZE):
                original_size += len(chunk)
                if original_size > pc.MAX_ENTRY_SIZE:
                    raise HTTPException(status_code=422, detail=f"格納ファイルが大きすぎます: {source.name}")
                digest.update(chunk)
                output.write(compressor.compress(chunk))
            output.write(compressor.flush())
        return temp, original_size, digest.hexdigest()
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def requires_upgrade(pc, connection: sqlite3.Connection) -> bool:
    pc._validate_header(connection)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    entries_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'"
    ).fetchone()
    entries_sql = str(entries_sql_row[0] or "") if entries_sql_row else ""
    has_legacy_entries = connection.execute(
        "SELECT 1 FROM entries WHERE compression='deflate' LIMIT 1"
    ).fetchone() is not None
    return version != pc.FORMAT_VERSION or "zstd" not in entries_sql.lower() or has_legacy_entries


def stage_legacy(pc, container: Path) -> Path | None:
    with closing(pc._connect(container, readonly=True)) as source:
        if not requires_upgrade(pc, source):
            return None
        pc.validate_container(container)
        target = container.with_name(f".{container.name}.staging-{os.getpid()}")
        target.unlink(missing_ok=True)
        try:
            with closing(pc._connect(target)) as staged:
                source.backup(staged)
                with staged:
                    staged.execute("ALTER TABLE entries RENAME TO legacy_entries")
                    staged.execute(
                        "CREATE TABLE entries (path TEXT PRIMARY KEY, kind TEXT NOT NULL "
                        "CHECK(kind IN ('file','directory')), compression TEXT NOT NULL "
                        "CHECK(compression IN ('none','deflate','zstd')), original_size INTEGER NOT NULL "
                        "CHECK(original_size >= 0), sha256 TEXT NOT NULL, data BLOB NOT NULL)"
                    )
                    staged.execute("INSERT INTO entries SELECT * FROM legacy_entries")
                    staged.execute("DROP TABLE legacy_entries")
                    staged.execute(f"PRAGMA user_version={pc.FORMAT_VERSION}")
            return target
        except Exception:
            target.unlink(missing_ok=True)
            raise


def publish_stage(pc, stage: Path, container: Path) -> None:
    pc.validate_container(stage, staging=True)
    with stage.open("r+b") as stream:
        os.fsync(stream.fileno())
    stage.replace(container)


def extract_file(pc, connection: sqlite3.Connection, row: sqlite3.Row, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    written = 0
    blob_row = connection.execute("SELECT rowid FROM entries WHERE path=?", (row["path"],)).fetchone()
    method = row["compression"]
    decompressor = zlib.decompressobj() if method == "deflate" else (
        zstd.ZstdDecompressor().decompressobj() if method == "zstd" else None
    )
    try:
        with (
            connection.blobopen("entries", "data", blob_row[0], readonly=True) as blob,
            destination.open("wb") as output,
        ):
            while chunk := blob.read(pc.CHUNK_SIZE):
                pending = chunk
                while pending:
                    data = (decompressor.decompress(pending, pc.CHUNK_SIZE) if method == "deflate"
                            else decompressor.decompress(pending) if decompressor else pending)
                    pending = decompressor.unconsumed_tail if method == "deflate" else b""
                    written += len(data)
                    if written > row["original_size"]:
                        raise ValueError("expanded size exceeds declaration")
                    digest.update(data)
                    output.write(data)
            if decompressor:
                data = decompressor.flush(pc.MAX_ENTRY_SIZE - written + 1) if method == "deflate" else b""
                written += len(data)
                digest.update(data)
                output.write(data)
                if not decompressor.eof or decompressor.unused_data:
                    raise ValueError("invalid compressed stream")
        if method not in ("none", "deflate", "zstd") or written != row["original_size"] or digest.hexdigest() != row["sha256"]:
            raise ValueError("size or SHA-256 mismatch")
    except (OSError, zlib.error, zstd.ZstdError, ValueError) as error:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"破損したエントリです: {row['path']}: {error}") from error

def plain_metadata(pc, source: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as stream:
        while chunk := stream.read(pc.CHUNK_SIZE):
            size += len(chunk)
            if size > pc.MAX_ENTRY_SIZE:
                raise HTTPException(status_code=422, detail=f"格納ファイルが大きすぎます: {source.name}")
            digest.update(chunk)
    return size, digest.hexdigest()

def write_blob(
    pc,
    connection: sqlite3.Connection, relative: str, source: Path, compression: str, size: int, digest: str
) -> None:
    stored_size = source.stat().st_size
    connection.execute(
        "INSERT INTO entries VALUES (?, 'file', ?, ?, ?, zeroblob(?)) "
        "ON CONFLICT(path) DO UPDATE SET kind='file', compression=excluded.compression, "
        "original_size=excluded.original_size, sha256=excluded.sha256, data=excluded.data",
        (relative, compression, size, digest, stored_size),
    )
    rowid = connection.execute("SELECT rowid FROM entries WHERE path=?", (relative,)).fetchone()[0]
    with connection.blobopen("entries", "data", rowid, readonly=False) as blob, source.open("rb") as stream:
        while chunk := stream.read(pc.CHUNK_SIZE):
            blob.write(chunk)

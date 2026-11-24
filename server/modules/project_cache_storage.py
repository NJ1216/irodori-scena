"""Incremental cache publication and load-time SQLite compaction."""

from __future__ import annotations

import json
import os
import uuid
from contextlib import closing
from pathlib import Path

from server.modules import project_container as container_io
from server.registry import deps

SCRATCH_PROVENANCE = "media/cache/timeline-v1/.provenance.json"


def _record_scratch_interval(root: Path, relative: str, provenance: dict[str, object]) -> None:
    manifest = root / SCRATCH_PROVENANCE
    with container_io._SYNC_LOCK:
        try:
            records = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(records, dict):
                records = {}
        except (OSError, ValueError):
            records = {}
        records[relative] = [
            str(provenance["planId"]), int(provenance["startFrame"]),
            int(provenance["endFrame"]), provenance.get("targets"),
        ]
        manifest.parent.mkdir(parents=True, exist_ok=True)
        temporary = manifest.with_name(f"{manifest.name}.tmp-{os.getpid()}")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(records, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(manifest)
        finally:
            temporary.unlink(missing_ok=True)


def persist_derived_cache(path: Path, provenance: dict[str, object] | None = None) -> None:
    saved = deps.ACTIVE_PROJECT_PATH
    root = deps.ACTIVE_PROJECT_ROOT
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return
    if not container_io._derived_audio(relative) or path.suffix.lower() != ".wav" or not path.is_file():
        return
    if relative.startswith("media/cache/timeline-v1/"):
        return
    if saved is None:
        if provenance is not None:
            _record_scratch_interval(root, relative, provenance)
        return
    if not saved.exists():
        return
    with container_io._SYNC_LOCK:
        cached = container_io._load_sync_index(saved, root)
        stage = container_io._stage_legacy(saved)
        try:
            _persist_cache(saved, stage, root, path, relative, provenance, cached)
        finally:
            if stage is not None:
                stage.unlink(missing_ok=True)


def _persist_cache(saved, stage, root, path, relative, provenance, cached):
    with closing(container_io._connect(stage or saved)) as connection:
        container_io._create_schema(connection)
        stat = path.stat()
        indexed = cached.get(relative) if cached is not None else None
        unchanged = (
            isinstance(indexed, dict)
            and indexed.get("size") == stat.st_size
            and indexed.get("mtimeNs") == stat.st_mtime_ns
            and indexed.get("inode") == stat.st_ino
        )
        digest = str(indexed["sha256"]) if unchanged else ""
        with connection:
            if not unchanged:
                compressed, size, digest = container_io._compressed_copy(path)
                try:
                    use_compression = compressed.stat().st_size < size
                    container_io._write_blob(
                        connection, relative, compressed if use_compression else path,
                        "zstd" if use_compression else "none", size, digest,
                    )
                finally:
                    compressed.unlink(missing_ok=True)
            if provenance is not None:
                connection.execute(
                    "INSERT OR REPLACE INTO cache_provenance VALUES (?,?,?,?,?)",
                    (
                        relative, str(provenance["planId"]), int(provenance["startFrame"]),
                        int(provenance["endFrame"]), json.dumps(provenance.get("targets")),
                    ),
                )
    if stage is not None:
        container_io._publish_stage(stage, saved)
    next_index = dict(cached or {})
    next_index[relative] = container_io._file_metadata(path, digest)
    container_io._refresh_sync_index(saved, root, next_index)


def compact_container_entries(
    saved: Path, retained: set[str], provenance_rows: list[tuple[str, str, int, int, str]] | None = None,
) -> bool:
    """Repack only when needed; preserve the original on failure."""
    with container_io._SYNC_LOCK:
        with closing(container_io._connect(saved, readonly=True)) as source:
            names = {row[0] for row in source.execute("SELECT path FROM entries")}
            free_pages = int(source.execute("PRAGMA freelist_count").fetchone()[0])
            if names <= retained and free_pages == 0:
                return False
            staging = saved.with_name(f".{saved.name}.staging-{uuid.uuid4().hex}")
            try:
                with closing(container_io._connect(staging)) as target:
                    source.backup(target)
                    source.close()
                    with target:
                        target.executemany("DELETE FROM entries WHERE path=?", ((name,) for name in names - retained))
                        container_io._create_schema(target)
                        if provenance_rows:
                            target.executemany("INSERT OR REPLACE INTO cache_provenance VALUES (?,?,?,?,?)", provenance_rows)
                        target.execute("DELETE FROM cache_provenance WHERE path NOT IN (SELECT path FROM entries)")
                    target.execute("VACUUM")
                container_io.validate_container(staging, staging=True)
                with staging.open("r+b") as stream:
                    os.fsync(stream.fileno())
                staging.replace(saved)
                return True
            finally:
                staging.unlink(missing_ok=True)


deps.register(__name__, ["compact_container_entries", "persist_derived_cache"])

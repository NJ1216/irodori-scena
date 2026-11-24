#!/usr/bin/env python3
"""Non-destructively convert legacy .scena directories to v1 container files."""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.app import deps  # noqa: E402
from server.modules import project_container  # noqa: E402


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(project_container.CHUNK_SIZE):
            value.update(chunk)
    return value.hexdigest()


def inventory(root: Path) -> tuple[dict[str, str], int, int]:
    included: dict[str, str] = {}
    excluded_count = 0
    excluded_size = 0
    for directory, names, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        for name in list(names):
            relative = PurePosixPath((parent / name).relative_to(root).as_posix())
            if not project_container._included(relative):
                subtree = parent / name
                for child in subtree.rglob("*"):
                    if child.is_file() and not child.is_symlink():
                        excluded_count += 1
                        excluded_size += child.stat().st_size
                names.remove(name)
        for name in files:
            path = parent / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if path.is_symlink():
                raise ValueError(f"symbolic link is not supported: {relative}")
            if project_container._included(relative):
                included[relative.as_posix()] = digest(path)
            else:
                excluded_count += 1
                excluded_size += path.stat().st_size
    return included, excluded_count, excluded_size


def convert(source: Path, destination: Path) -> tuple[int, int, int, int]:
    if not source.is_dir() or source.suffix.lower() != ".scena":
        raise ValueError(f"not a legacy .scena directory: {source}")
    if destination.exists():
        raise FileExistsError(destination)
    source_hashes, excluded_count, excluded_size = inventory(source)
    if "project.json" not in source_hashes:
        raise ValueError("project.json is missing")
    deps.StudioProjectModel.model_validate_json((source / "project.json").read_text(encoding="utf-8"))
    project_container.sync_container(destination, source)
    try:
        with tempfile.TemporaryDirectory(prefix="scena-migration-") as raw:
            extracted = Path(raw) / "project"
            project_container.extract_container(destination, extracted)
            roundtrip, _, _ = inventory(extracted)
            if roundtrip != source_hashes:
                raise ValueError("round-trip file hash comparison failed")
            deps.StudioProjectModel.model_validate_json((extracted / "project.json").read_text(encoding="utf-8"))
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return len(source_hashes), excluded_count, excluded_size, destination.stat().st_size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", nargs="?", type=Path, default=Path("userproject"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source_root = args.source.resolve()
    output = (args.output or source_root / "migrated").resolve()
    output.mkdir(parents=True, exist_ok=True)
    sources = sorted(path for path in source_root.glob("*.scena") if path.is_dir())
    failures = 0
    for source in sources:
        destination = output / source.name
        try:
            files, excluded, excluded_bytes, stored = convert(source, destination)
            original = sum(path.stat().st_size for path in source.rglob("*") if path.is_file() and not path.is_symlink())
            print(f"OK {source.name}: {files} entries, excluded {excluded} files/{excluded_bytes} bytes, {original} -> {stored} bytes")
        except Exception as error:
            failures += 1
            print(f"FAILED {source.name}: {error}")
    print(f"Converted {len(sources) - failures}/{len(sources)} projects into {output}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

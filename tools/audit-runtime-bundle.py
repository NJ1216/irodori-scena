#!/usr/bin/env python3
"""Audit frozen sidecars and release artifacts for avoidable bulk."""

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

LARGE_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_BASELINE_BYTES = 1_400_000_000
FORBIDDEN_PARTS = {
    "admin", "cluster", "eval", "mcp", "bench-corpora", "mlx_audio",
    "pyarrow", "pandas", "cv2", "sounddevice", "markitdown", "pdfminer", "pypdfium2",
}


def file_size(path: Path) -> int:
    return sum(
        item.stat().st_size
        for item in path.rglob("*")
        if item.is_file() and not item.is_symlink()
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def audit(root: Path, baseline: int | None = None) -> dict[str, object]:
    paths = sorted(root.rglob("*"))
    files = [path for path in paths if path.is_file() and not path.is_symlink()]
    symlinks = [path for path in paths if path.is_symlink()]
    broken_links = [path for path in symlinks if not path.exists()]
    large = [path for path in files if path.stat().st_size >= LARGE_FILE_BYTES]
    hashes: dict[tuple[int, str], list[Path]] = defaultdict(list)
    for path in large:
        hashes[(path.stat().st_size, hash_file(path))].append(path)
    duplicates = [paths for paths in hashes.values() if len(paths) > 1]
    forbidden = [
        path for path in files
        if any(part.lower().replace("-", "_") in FORBIDDEN_PARTS for part in path.parts)
    ]
    total = file_size(root)
    result: dict[str, object] = {
        "root": str(root), "bytes": total,
        "largest": [
            {"bytes": path.stat().st_size, "path": str(path.relative_to(root))}
            for path in sorted(files, key=lambda item: item.stat().st_size, reverse=True)[:20]
        ],
        "duplicateLargeFiles": [
            [str(path.relative_to(root)) for path in sorted(paths)] for paths in duplicates
        ],
        "forbiddenFiles": [str(path.relative_to(root)) for path in forbidden[:100]],
        "symlinks": [str(path.relative_to(root)) for path in symlinks],
        "brokenSymlinks": [str(path.relative_to(root)) for path in broken_links],
    }
    if baseline:
        result["reductionPercent"] = round((1 - total / baseline) * 100, 2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--baseline-bytes", type=int, default=None)
    parser.add_argument("--require-30-percent", action="store_true")
    args = parser.parse_args()
    baseline = args.baseline_bytes or (DEFAULT_BASELINE_BYTES if args.require_30_percent else None)
    result = audit(args.root, baseline)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failed = bool(
        result["duplicateLargeFiles"]
        or result["forbiddenFiles"]
        or result["brokenSymlinks"]
    )
    if args.require_30_percent and result.get("reductionPercent", 0) < 30:
        failed = True
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

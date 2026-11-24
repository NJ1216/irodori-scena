from __future__ import annotations

import hashlib
from pathlib import Path

def _local_fingerprint(path: Path) -> str | None:
    try:
        rows = [f"{item.relative_to(path)}:{item.stat().st_size}:{item.stat().st_mtime_ns}"
                for item in sorted(path.rglob("*")) if item.is_file()]
    except OSError:
        return None
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()
def _local_root_signature(path: Path) -> dict[str, int | str] | None:
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except OSError:
        return None
    return {"path": str(resolved), "device": stat.st_dev, "inode": stat.st_ino,
            "size": stat.st_size, "modifiedNs": stat.st_mtime_ns}

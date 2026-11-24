from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _signature(path: Path) -> dict[str, Any] | None:
    try:
        resolved = path.resolve(strict=True)
        stat = resolved.stat()
    except OSError:
        return None
    return {"path": str(resolved), "device": stat.st_dev, "inode": stat.st_ino,
            "size": stat.st_size, "modifiedNs": stat.st_mtime_ns}


def _asset_usage(roots: list[Path]) -> tuple[int, list[dict[str, Any]]]:
    """Measure file targets once, including HF file links but never directory links."""
    total = 0
    seen: set[tuple[int, int]] = set()
    signatures: list[dict[str, Any]] = []
    for root in roots:
        candidates: list[Path] = [root] if root.is_file() else []
        if root.is_dir():
            for directory, names, files in os.walk(root, topdown=True, followlinks=False):
                current = Path(directory)
                names[:] = [name for name in names if not (current / name).is_symlink()]
                candidates.extend(current / name for name in files)
        for candidate in candidates:
            try:
                if candidate.is_symlink() and candidate.resolve(strict=True).is_dir():
                    continue
                resolved = candidate.resolve(strict=True)
                stat = resolved.stat()
                if not resolved.is_file():
                    continue
            except OSError:
                continue
            signatures.append({"path": str(resolved), "device": stat.st_dev, "inode": stat.st_ino,
                               "size": stat.st_size, "modifiedNs": stat.st_mtime_ns})
            identity = (stat.st_dev, stat.st_ino)
            if identity not in seen:
                seen.add(identity)
                total += stat.st_size
    signatures.sort(key=lambda item: (item["path"], item["device"], item["inode"]))
    return total, signatures


def refresh_external_model_disk_usage(card: dict[str, Any]) -> bool:
    if card.get("source") != "external" or not card.get("libraryId"):
        return False
    roots = [Path(str(card[key])) for key in ("path", "codecPath", "tokenizerPath") if card.get(key)]
    required = (Path(str(card.get("path", ""))) / "model.safetensors",
                Path(str(card.get("codecPath", ""))) / "weights.pth")
    root_signatures = [_signature(path) for path in roots]
    if not roots or any(not path.is_file() for path in required) or any(value is None for value in root_signatures):
        return False
    quick_signature = {"roots": root_signatures, "required": [_signature(path) for path in required]}
    cached = card.get("diskUsageFingerprint")
    if isinstance(cached, dict) and cached.get("quick") == quick_signature and card.get("diskBytes") is not None:
        return False
    disk_bytes, signatures = _asset_usage(roots)
    fingerprint = {"version": 3, "quick": quick_signature, "assets": signatures}
    card["diskBytes"] = disk_bytes
    card["diskUsageFingerprint"] = fingerprint
    return True

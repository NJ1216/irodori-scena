from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def remove_variant_files(variant: dict[str, Any], variants: list[dict[str, Any]], models_root: Path) -> None:
    if not variant.get("path"):
        return
    candidate = Path(str(variant["path"])).resolve()
    try:
        candidate.relative_to(models_root.resolve())
    except ValueError:
        return
    if not candidate.is_dir():
        return
    shared = any(other is not variant and Path(str(other.get("path", ""))).resolve() == candidate for other in variants)
    if not shared:
        shutil.rmtree(candidate)
        return
    checkpoint = candidate / str(variant.get("checkpointFile") or "model.safetensors")
    checkpoint.unlink(missing_ok=True)
    try:
        checkpoint.parent.rmdir()
    except OSError:
        pass

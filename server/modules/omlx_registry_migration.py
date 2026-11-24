from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any


def _registry_runtime_key(item: dict[str, Any], index: int) -> str:
    path = item.get("path")
    if not path:
        return str(item.get("id") or f"invalid-{index}")
    try:
        return str(Path(str(path)).expanduser().resolve())
    except (OSError, RuntimeError):
        return str(path)


def normalize_registry(registry: dict[str, Any], runtime: SimpleNamespace) -> bool:
    runtimes = registry.get("runtimes")
    if not isinstance(runtimes, list):
        registry["runtimes"] = []
        return True
    groups: dict[str, list[dict[str, Any]]] = {}
    for index, item in enumerate(runtimes):
        if not isinstance(item, dict):
            continue
        key = _registry_runtime_key(item, index)
        groups.setdefault(key, []).append(item)
    normalized, aliases = [], {}
    for group in groups.values():
        preferred = max(group, key=lambda item: item.get("source") != "migrated")
        other_ids = {x["id"] for x in group if x.get("id") != preferred.get("id")}
        if other_ids:
            preferred["aliases"] = sorted(set(preferred.get("aliases", [])) | other_ids)
        normalized.append(preferred)
        for item in group:
            if item.get("id"):
                aliases[item["id"]] = preferred.get("id")
    active = registry.get("activeRuntimeId")
    registry["activeRuntimeId"] = aliases.get(active, active)
    changed = normalized != runtimes
    registry["runtimes"] = normalized
    return changed


def migrate_registry(registry: dict[str, Any], runtime: SimpleNamespace) -> bool:
    changed = False
    known = {item.get("path") for item in registry["runtimes"]}
    for path in runtime.base().glob("omlx-*"):
        if not (path / ".ready").is_file() or str(path) in known:
            continue
        suffix = path.name.removeprefix("omlx-")
        runtime_id = runtime.recommended_id() if suffix == runtime.fingerprint() else f"legacy-{suffix}"
        registry["runtimes"].append(
            {
                "id": runtime_id,
                "displayName": "SCENA動作確認版"
                if runtime_id == runtime.recommended_id()
                else f"既存のoMLX ({suffix[:12]})",
                "omlxVersion": runtime.installed_version(path) or "不明",
                "source": "scena" if runtime_id == runtime.recommended_id() else "migrated",
                "verification": "verified",
                "state": "ready",
                "path": str(path),
                "diskBytes": runtime.size(path),
                "installedAt": path.stat().st_mtime,
                "error": None,
                "commit": None,
                "gitRef": None,
            }
        )
        registry["activeRuntimeId"] = registry.get("activeRuntimeId") or runtime_id
        changed = True
    return changed

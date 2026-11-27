"""Merge adjacent render mutations into one Undo boundary."""

from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Iterable
from typing import Any


def _project_revision(snapshot: dict[str, Any], blob_root: Path) -> int | None:
    digest = snapshot["files"].get("project.json")
    if not digest:
        return None
    try:
        return int(json.loads((blob_root / digest).read_text(encoding="utf-8"))["revision"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _merge_media_targets(entry: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> bool:
    if before.get("includeMedia") and before.get("mediaTargets") is None:
        if entry["before"].get("includeMedia") and entry["before"].get("mediaTargets") is not None:
            return False
        if not entry["before"].get("includeMedia"):
            entry["before"] = {**entry["before"], "includeMedia": True, "mediaTargets": None, "files": {**entry["before"]["files"], **{path: digest for path, digest in before["files"].items() if path.startswith("media/")}}}
        entry["after"] = after
        return True
    if entry["before"].get("includeMedia") and entry["before"].get("mediaTargets") is None:
        if before.get("mediaTargets") is None:
            entry["after"] = after
            return True
        after_media = {path: digest for path, digest in entry["after"]["files"].items() if path.startswith("media/")}
        for target in before["mediaTargets"]:
            prefix = f"media/{target}"
            after_media = {path: digest for path, digest in after_media.items() if path != prefix and not path.startswith(f"{prefix}/")}
            after_media.update({path: digest for path, digest in after["files"].items() if path == prefix or path.startswith(f"{prefix}/")})
        entry["after"] = {**after, "includeMedia": True, "mediaTargets": None, "files": {**{path: digest for path, digest in after["files"].items() if not path.startswith("media/")}, **after_media}}
        return True
    old_targets = entry["before"].get("mediaTargets") or []
    new_targets = before.get("mediaTargets") or []
    targets = list(dict.fromkeys([*old_targets, *new_targets]))
    added = set(new_targets) - set(old_targets)
    before_media = {
        path: digest for path, digest in before["files"].items()
        if any(path == f"media/{target}" or path.startswith(f"media/{target}/") for target in added)
    }
    after_media = {path: digest for path, digest in entry["after"]["files"].items() if path.startswith("media/")}
    for target in new_targets:
        prefix = f"media/{target}"
        after_media = {path: digest for path, digest in after_media.items() if path != prefix and not path.startswith(f"{prefix}/")}
        after_media.update({path: digest for path, digest in after["files"].items() if path == prefix or path.startswith(f"{prefix}/")})
    entry["before"] = {**entry["before"], "includeMedia": bool(targets), "mediaTargets": targets, "files": {**entry["before"]["files"], **before_media}}
    entry["after"] = {**after, "includeMedia": bool(targets), "mediaTargets": targets, "files": {**{path: digest for path, digest in after["files"].items() if not path.startswith("media/")}, **after_media}}
    return True


def coalesce_auto_render(entries: list[dict[str, Any]], cursor: int, scope: str, before: dict[str, Any], after: dict[str, Any], base_revision: int | None, blob_root: Path) -> bool:
    if scope != "script" or base_revision is None or cursor != len(entries) or not entries:
        return False
    entry = entries[-1]
    boundary = entry["after"]
    if boundary["projectRoot"] != before["projectRoot"] or boundary["files"].get("project.json") != before["files"].get("project.json"):
        return False
    if entry.get("autoRenderBaseRevision") != base_revision and _project_revision(boundary, blob_root) != base_revision:
        return False
    if not _merge_media_targets(entry, before, after):
        return False
    entry["autoRenderBaseRevision"] = base_revision
    entry["generationGroupId"] = None
    return True


def coalesce_generation_group(entries: list[dict[str, Any]], cursor: int, scope: str, before: dict[str, Any], after: dict[str, Any], group_id: str | None) -> bool:
    if scope != "script" or group_id is None or cursor != len(entries) or not entries:
        return False
    entry = entries[-1]
    boundary = entry["after"]
    if entry.get("generationGroupId") != group_id or boundary["projectRoot"] != before["projectRoot"]:
        return False
    if boundary["files"].get("project.json") != before["files"].get("project.json"):
        return False
    targets = list(dict.fromkeys([*(entry["before"].get("mediaTargets") or []), *(before.get("mediaTargets") or [])]))
    added_targets = set(before.get("mediaTargets") or []) - set(entry["before"].get("mediaTargets") or [])
    before_media = {
        path: digest
        for path, digest in before["files"].items()
        if any(path == f"media/{target}" or path.startswith(f"media/{target}/") for target in added_targets)
    }
    after_media = {path: digest for path, digest in entry["after"]["files"].items() if path.startswith("media/")}
    for target in before.get("mediaTargets") or []:
        prefix = f"media/{target}"
        after_media = {path: digest for path, digest in after_media.items() if path != prefix and not path.startswith(f"{prefix}/")}
        after_media.update({path: digest for path, digest in after["files"].items() if path == prefix or path.startswith(f"{prefix}/")})
    entry["before"] = {
        **entry["before"],
        "mediaTargets": targets,
        "files": {**entry["before"]["files"], **before_media},
    }
    entry["after"] = {
        **after,
        "mediaTargets": targets,
        "files": {**{path: digest for path, digest in after["files"].items() if not path.startswith("media/")}, **after_media},
    }
    return True


def prune_unreferenced_blobs(blob_root: Path, history: dict[str, list[dict[str, Any]]], protected: Iterable[str] = ()) -> None:
    """Delete blobs no entry references, sparing digests held by in-flight captures."""
    referenced = set(protected)
    referenced.update(
        digest
        for scope_entries in history.values()
        for entry in scope_entries
        for snapshot in (entry["before"], entry["after"])
        for digest in snapshot["files"].values()
    )
    for blob in blob_root.iterdir():
        if blob.is_file() and blob.name not in referenced:
            blob.unlink(missing_ok=True)

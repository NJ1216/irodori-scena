"""Resolve the media boundary owned by a history mutation."""

from __future__ import annotations

from fastapi import HTTPException

from server.registry import deps


async def batch_delete_media_targets(request) -> list[str] | None:
    if request.method != "POST" or request.url.path not in {"/api/lines/batch-delete", "/api/lines/cleanup-takes"}:
        return None
    try:
        payload = await request.json()
        line_ids = [str(value) for value in payload.get("line_ids", []) if str(value)]
        if not line_ids or len(line_ids) != len(set(line_ids)):
            return None
        return [f"takes/{deps.safe_segment(line_id)}" for line_id in line_ids]
    except (AttributeError, TypeError, ValueError, HTTPException):
        return None


def scene_delete_media_targets(path: str, method: str) -> list[str] | None:
    if method != "DELETE" or not path.startswith("/api/scenes/") or path.count("/") != 3:
        return None
    scene_id = path.rsplit("/", 1)[-1]
    try:
        scene = next((item for item in deps.read_project().get("scenes", []) if item.get("id") == scene_id), None)
        if scene is None:
            return None
        return [f"takes/{deps.safe_segment(str(line['id']))}" for line in scene.get("lines", [])]
    except (KeyError, TypeError, ValueError, HTTPException):
        return None


def line_delete_media_targets(path: str, method: str) -> list[str] | None:
    parts = path.split("/")
    if method != "DELETE" or len(parts) != 6 or parts[:3] != ["", "api", "scenes"] or parts[4] != "lines":
        return None
    try:
        return [f"takes/{deps.safe_segment(parts[5])}"]
    except (ValueError, HTTPException):
        return None


def line_take_media_targets(path: str, method: str) -> list[str] | None:
    parts = path.split("/")
    if method not in {"POST", "DELETE"} or len(parts) < 5 or parts[:3] != ["", "api", "lines"]:
        return None
    if len(parts) == 5 and parts[4] in {"generate", "regenerate"}:
        line_id = parts[3]
    elif len(parts) == 6 and parts[4] == "takes" and method == "DELETE":
        line_id = parts[3]
    else:
        return None
    try:
        return [f"takes/{deps.safe_segment(line_id)}"]
    except (ValueError, HTTPException):
        return None

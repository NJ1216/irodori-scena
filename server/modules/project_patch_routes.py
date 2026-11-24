from __future__ import annotations

from fastapi.responses import JSONResponse

from server.registry import deps


def _patch(kind: str, request: deps.ProjectPatch, line_id: str | None = None):
    revision = deps.apply_project_patch(kind, request.base_revision, request.changes, line_id)
    if revision is None:
        current = deps.read_project()
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "project_revision_conflict",
                    "message": "別の変更が先に保存されました。",
                    "currentRevision": current["revision"],
                    "currentProject": current,
                }
            },
        )
    return {"revision": revision}


def _revision_conflict():
    current = deps.read_project()
    return JSONResponse(
        status_code=409,
        content={"detail": {"code": "project_revision_conflict", "message": "別の変更が先に保存されました。", "currentRevision": current["revision"], "currentProject": current}},
    )


@deps.app.patch("/api/project/metadata")
def patch_project_metadata(request: deps.ProjectPatch):
    return _patch("metadata", request)


@deps.app.patch("/api/project/settings")
def patch_project_settings(request: deps.ProjectPatch):
    return _patch("settings", request)


@deps.app.patch("/api/lines/{line_id}")
def patch_project_line(line_id: str, request: deps.ProjectPatch):
    return _patch("line", request, line_id)


@deps.app.patch("/api/characters/order", response_model=deps.StudioProjectModel)
def patch_character_order(request: deps.CharacterOrderRequest):
    project = deps.apply_character_order(request.base_revision, request.character_ids)
    return project if project is not None else _revision_conflict()

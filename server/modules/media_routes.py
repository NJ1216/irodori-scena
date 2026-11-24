from __future__ import annotations

from server.app_deps import Path, HTTPException, FileResponse
from server.registry import deps


def serve_media_file(root: Path, media_path: str) -> FileResponse:
    candidate = (root / media_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Media file was not found.") from error
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Media file was not found.")
    return FileResponse(candidate)


@deps.app.get("/media/{media_path:path}")
def get_project_media(media_path: str) -> FileResponse:
    return serve_media_file(deps.MEDIA_ROOT, media_path)


@deps.app.head("/media/{media_path:path}")
def head_project_media(media_path: str) -> FileResponse:
    return serve_media_file(deps.MEDIA_ROOT, media_path)


@deps.app.get("/global-media/{media_path:path}")
def get_global_media(media_path: str) -> FileResponse:
    return serve_media_file(deps.GLOBAL_MEDIA_ROOT, media_path)


@deps.app.head("/global-media/{media_path:path}")
def head_global_media(media_path: str) -> FileResponse:
    return serve_media_file(deps.GLOBAL_MEDIA_ROOT, media_path)


deps.register(__name__, ["get_global_media", "get_project_media", "head_global_media", "head_project_media", "serve_media_file"])

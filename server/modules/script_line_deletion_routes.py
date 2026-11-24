from __future__ import annotations

import threading
from server.app_deps import shutil, Path, Any, HTTPException
from server.registry import deps

def _discard_staged(paths: list[Path]) -> None:
    for path in paths:
        shutil.rmtree(path, ignore_errors=True)


@deps.app.post("/api/lines/batch-delete")
def delete_lines(request: dict[str, Any]) -> dict[str, Any]:
    """Commit all line removals together; delete their media after responding."""
    line_ids = [str(value) for value in request.get("line_ids", []) if str(value)]
    if not line_ids or len(line_ids) != len(set(line_ids)):
        raise HTTPException(status_code=422, detail="削除する発話行を重複なく指定してください。")
    project = deps.read_project()
    existing = {str(line.get("id", "")) for scene in project.get("scenes", []) for line in scene.get("lines", [])}
    missing = set(line_ids) - existing
    if missing:
        raise HTTPException(status_code=404, detail="削除する発話行が見つかりません。")
    cleanup = deps.MEDIA_ROOT / ".cleanup" / deps.new_id("lines")
    staged: list[Path] = []
    cleanup.mkdir(parents=True, exist_ok=True)
    try:
        for line_id in line_ids:
            source = deps.MEDIA_ROOT / "takes" / deps.safe_segment(line_id)
            if source.exists():
                destination = cleanup / source.name
                source.replace(destination)
                staged.append(destination)
        selected = set(line_ids)
        for scene in project.get("scenes", []):
            scene["lines"] = [line for line in scene.get("lines", []) if str(line.get("id", "")) not in selected]
            deps.normalize_scene_cues(scene)
        deps.write_project(project)
    except Exception:
        for path in staged:
            path.replace(deps.MEDIA_ROOT / "takes" / path.name)
        shutil.rmtree(cleanup, ignore_errors=True)
        raise
    threading.Thread(target=_discard_staged, args=([cleanup],), daemon=True).start()
    return project


deps.register(__name__, ["delete_lines"])

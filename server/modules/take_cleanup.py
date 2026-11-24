from __future__ import annotations

from server.app_deps import shutil, Any, HTTPException
from server.registry import deps


def clear_project_takes(project: dict[str, Any]) -> dict[str, Any]:
    """Remove all Take media atomically; reclaim SQLite pages on the next load."""
    takes_root = (deps.MEDIA_ROOT / "takes").resolve()
    staged = deps.MEDIA_ROOT / ".cleanup" / deps.new_id("takes")
    moved = False
    try:
        if takes_root.exists():
            staged.parent.mkdir(parents=True, exist_ok=True)
            takes_root.replace(staged)
            moved = True
        for scene in project.get("scenes", []):
            for line in scene.get("lines", []):
                line["takes"] = []
                line["selectedTakeId"] = None
                line.pop("archivedTakes", None)
        saved = deps.write_project(project)
    except Exception:
        if moved and staged.exists():
            takes_root.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(takes_root)
        raise
    shutil.rmtree(staged, ignore_errors=True)
    try:
        staged.parent.rmdir()
    except OSError:
        pass
    return saved


deps.register(__name__, ["clear_project_takes"])


def cleanup_line_takes(project: dict[str, Any], line_ids: list[str], mode: str) -> dict[str, Any]:
    """Stage only removed take files, then save all requested lines in one edit."""
    if mode not in {"unselected", "all"} or not line_ids or len(line_ids) != len(set(line_ids)):
        raise HTTPException(status_code=422, detail="Invalid take cleanup request.")
    lines = {str(line.get("id")): line for scene in project.get("scenes", []) for line in scene.get("lines", [])}
    if any(line_id not in lines for line_id in line_ids):
        raise HTTPException(status_code=404, detail="Dialogue line not found.")
    staged_root = deps.MEDIA_ROOT / ".cleanup" / deps.new_id("selected-takes")
    staged: list[tuple[Any, Any]] = []
    try:
        for line_id in line_ids:
            line = lines[line_id]
            safe_line_id = deps.safe_segment(line_id)
            keep_id = line.get("selectedTakeId") if mode == "unselected" else None
            kept = []
            for take in line.get("takes", []):
                if take.get("id") == keep_id:
                    kept.append(take)
                    continue
                audio_url = str(take.get("audioUrl", ""))
                if audio_url.startswith("/media/takes/"):
                    source = (deps.MEDIA_ROOT / audio_url.removeprefix("/media/")).resolve()
                    try:
                        source.relative_to((deps.MEDIA_ROOT / "takes").resolve())
                    except ValueError as error:
                        raise HTTPException(status_code=500, detail="Take audio path was invalid.") from error
                    if source.exists():
                        destination = staged_root / safe_line_id / source.name
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        source.replace(destination)
                        staged.append((source, destination))
            line["takes"] = kept
            line["selectedTakeId"] = keep_id if kept else None
            if mode == "all":
                line.pop("archivedTakes", None)
        saved = deps.write_project(project)
    except Exception:
        for source, destination in reversed(staged):
            source.parent.mkdir(parents=True, exist_ok=True)
            destination.replace(source)
        shutil.rmtree(staged_root, ignore_errors=True)
        raise
    shutil.rmtree(staged_root, ignore_errors=True)
    return saved


deps.register(__name__, ["cleanup_line_takes"])

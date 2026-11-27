from __future__ import annotations

from server.app_deps import Path, Any
from server.registry import deps


def remove_candidate_files(candidates: list[dict[str, Any]]) -> None:
    root = (deps.MEDIA_ROOT / "candidates").resolve()
    for candidate in candidates:
        path = Path(str(candidate.get("file", ""))).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        if path.is_file():
            path.unlink()


@deps.app.post("/api/characters/candidates/clear-scope")
def clear_candidate_scope(kind: str, emotion: str | None = None, reference_candidate_id: str | None = None) -> dict[str, Any]:
    with deps.VOICE_CANDIDATE_GENERATION_LOCK, deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        candidates = project.get("candidates", [])
        if kind == "baseline":
            ids = {str(item.get("id", "")) for item in candidates if item.get("kind", "baseline") == "baseline"}
            removed = [item for item in candidates if item.get("kind", "baseline") == "baseline" or item.get("referenceCandidateId") in ids]
        elif kind == "emotion" and emotion and reference_candidate_id:
            removed = [item for item in candidates if item.get("kind") == "emotion" and item.get("emotion") == emotion and item.get("referenceCandidateId") == reference_candidate_id]
        else:
            return project
        remove_candidate_files(removed)
        removed_ids = {id(item) for item in removed}
        project["candidates"] = [item for item in candidates if id(item) not in removed_ids]
        deps.write_project(project)
        return project


deps.register(__name__, ["clear_candidate_scope", "remove_candidate_files"])

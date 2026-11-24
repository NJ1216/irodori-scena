from __future__ import annotations

from server.app_deps import Any, HTTPException
from server.registry import deps

METADATA_FIELDS = frozenset({"title"})
SETTINGS_FIELDS = frozenset({
    "speechRate", "steps", "textCfg", "voiceCfg", "captionCfg", "seed",
    "quality", "lineGap", "llmBaseUrl", "llmModel", "emojiExpressions",
    "fillerRichness",
})
LINE_FIELDS = frozenset({
    "text", "stageDirection", "characterId", "speechRate", "gapSeconds",
    "enabled", "pronunciations", "selectedTakeId",
})
RENDER_INPUT_FIELDS = frozenset({"text", "stageDirection", "characterId", "speechRate"})


def _checked_changes(changes: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    unknown = set(changes) - allowed
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unsupported project fields: {', '.join(sorted(unknown))}")
    if not changes:
        raise HTTPException(status_code=422, detail="Project patch needs at least one change.")
    return changes


def apply_project_patch(kind: str, base_revision: int, changes: dict[str, Any], line_id: str | None = None) -> int | None:
    with deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        current_revision = int(project.get("revision", 0))
        if base_revision != current_revision:
            return None
        if kind == "metadata":
            project.update(_checked_changes(changes, METADATA_FIELDS))
        elif kind == "settings":
            project.setdefault("settings", {}).update(_checked_changes(changes, SETTINGS_FIELDS))
        elif kind == "line" and line_id is not None:
            _, line = deps.find_line(project, line_id)
            accepted = _checked_changes(changes, LINE_FIELDS)
            if RENDER_INPUT_FIELDS.intersection(accepted):
                line["selectedTakeId"] = None
            line.update(accepted)
        else:
            raise HTTPException(status_code=404, detail="Unknown project patch target.")
        deps.write_project(project, project_only=True)
        return int(project["revision"])


def apply_character_order(base_revision: int, character_ids: list[str]) -> dict[str, Any] | None:
    with deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        if base_revision != int(project.get("revision", 0)):
            return None
        characters = project.get("characters", [])
        existing_ids = [str(character.get("id", "")) for character in characters]
        if len(character_ids) != len(set(character_ids)):
            raise HTTPException(status_code=422, detail="Character order contains duplicate IDs.")
        if set(character_ids) != set(existing_ids) or len(character_ids) != len(existing_ids):
            raise HTTPException(status_code=422, detail="Character order must contain every saved character ID exactly once.")
        by_id = {str(character["id"]): character for character in characters}
        project["characters"] = [by_id[character_id] for character_id in character_ids]
        deps.write_project(project, project_only=True)
        return project


deps.register(__name__, ["apply_character_order", "apply_project_patch"])

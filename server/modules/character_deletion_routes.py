from __future__ import annotations

from server.app_deps import shutil, Any, HTTPException
from server.modules.pronunciation_dictionary import dictionary_transaction
from server.registry import deps

@deps.app.delete("/api/characters/{character_id}")
@dictionary_transaction
def delete_character(character_id: str) -> dict[str, Any]:
    project = deps.read_project()
    character = deps.find_character(project, character_id)
    delete_global = character.get("scope") == "global" or deps.project_character_matches_global(character)
    project["characters"] = [item for item in project.get("characters", []) if str(item.get("id", "")) != character_id]
    character_root = (
        deps.GLOBAL_MEDIA_ROOT / "characters" if delete_global else deps.MEDIA_ROOT / "characters"
    ).resolve()
    reference_dir = (character_root / deps.safe_segment(character_id)).resolve()
    try:
        reference_dir.relative_to(character_root)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Character reference directory was invalid.") from error
    global_characters = deps.read_global_characters() if delete_global else None
    pronunciations = deps.read_pronunciation_dictionary()
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []):
            if line.get("characterId") == character_id:
                deps.archive_line_takes(line)
                line["characterId"] = ""
    try:
        if global_characters is not None:
            deps.write_global_characters([item for item in global_characters if item.get("id") != character_id])
        deps.remove_character_pronunciations(character_id)
        deps.write_project(project)
    except Exception:
        if global_characters is not None:
            try:
                deps.write_global_characters(global_characters)
            except Exception:
                pass
        try:
            deps.write_pronunciation_dictionary(pronunciations)
        except Exception:
            pass
        raise
    try:
        deps.delete_cast_context(
            "global" if delete_global else "project",
            character_id,
            str(project.get("id", "default")),
        )
    except OSError:
        pass
    shutil.rmtree(reference_dir, ignore_errors=True)
    return project


deps.register(__name__, ["delete_character"])

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from server.registry import deps


def project_backup_snapshot(project: dict[str, Any]) -> dict[str, Any]:
    snapshot = json.loads(json.dumps(project, ensure_ascii=False))
    cast_ids = {
        str(line.get("characterId", ""))
        for scene in snapshot.get("scenes", [])
        if isinstance(scene, dict)
        for line in scene.get("lines", [])
        if isinstance(line, dict) and str(line.get("characterId", ""))
    }
    snapshot["characters"] = [
        character
        for character in snapshot.get("characters", [])
        if isinstance(character, dict) and str(character.get("id", "")) in cast_ids
    ]
    for character in snapshot["characters"]:
        character.pop("referenceFile", None)
    snapshot["pronunciationDictionary"] = deps.project_pronunciation_snapshot(snapshot)
    snapshot["candidates"] = []
    return snapshot


def project_backup_media(project: dict[str, Any]) -> list[Path]:
    urls: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if (
                    key in {"audioUrl", "referenceAudioUrl", "avatarUrl", "avatarThumbnailUrl", "avatarOriginalUrl"}
                    and isinstance(child, str)
                    and child.startswith("/media/")
                ):
                    urls.add(child)
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(project)
    sources: list[Path] = []
    for url in urls:
        source = deps.MEDIA_ROOT / url.removeprefix("/media/")
        try:
            source.resolve().relative_to(deps.MEDIA_ROOT.resolve())
        except ValueError:
            continue
        if source.is_file():
            sources.append(source)
    return sources


def materialize_cast_global_characters(project: dict[str, Any]) -> dict[str, Any]:
    cast_ids = {
        str(line.get("characterId", ""))
        for scene in project.get("scenes", [])
        if isinstance(scene, dict)
        for line in scene.get("lines", [])
        if isinstance(line, dict) and str(line.get("characterId", ""))
    }
    if not cast_ids:
        return project
    by_id = {str(item.get("id", "")): item for item in project.get("characters", []) if isinstance(item, dict)}
    local = [item for item in project.get("characters", []) if isinstance(item, dict) and item.get("scope") != "global"]
    local_ids = {str(item.get("id", "")) for item in local}
    for character_id in cast_ids - local_ids:
        source_character = by_id.get(character_id)
        if source_character is None or source_character.get("scope") != "global":
            continue
        source = Path(str(source_character.get("referenceFile", ""))).resolve()
        if not source.is_file():
            raise HTTPException(
                status_code=422, detail=f"Global character {source_character.get('name', '')} has no reference WAV."
            )
        target = deps.MEDIA_ROOT / "characters" / deps.safe_segment(character_id) / "reference.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        snapshot = dict(source_character)
        snapshot.update(
            {
                "scope": "project",
                "referenceAudioUrl": deps.media_url(target),
                "referenceFile": str(target),
                "audioHash": deps.audio_digest(target),
            }
        )

        def copy_avatar(source_url: str, target_name: str) -> Path | None:
            if not source_url.startswith("/global-media/"):
                return None
            avatar_source = (deps.GLOBAL_MEDIA_ROOT / source_url.removeprefix("/global-media/")).resolve()
            try:
                avatar_source.relative_to(deps.GLOBAL_MEDIA_ROOT.resolve())
            except ValueError:
                return None
            if not avatar_source.is_file():
                return None
            avatar_target = target.with_name(target_name)
            shutil.copy2(avatar_source, avatar_target)
            return avatar_target

        original_url = str(source_character.get("avatarOriginalUrl", ""))
        original_suffix = Path(original_url).suffix.lower()
        if original_suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            original_suffix = ".png"
        original_target = copy_avatar(original_url, f"avatar-original{original_suffix}")
        if original_target:
            snapshot["avatarOriginalUrl"] = deps.media_url(original_target)
        thumbnail_url = str(source_character.get("avatarThumbnailUrl") or source_character.get("avatarUrl", ""))
        thumbnail_target = copy_avatar(thumbnail_url, "avatar-thumbnail.png")
        if thumbnail_target:
            thumbnail_media_url = deps.media_url(thumbnail_target)
            snapshot.update({"avatarThumbnailUrl": thumbnail_media_url, "avatarUrl": thumbnail_media_url})
        local.append(snapshot)
    project["characters"] = local
    return project

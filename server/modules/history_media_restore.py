from __future__ import annotations

from server.app_deps import json, shutil, uuid4, Path, Any, HTTPException
from server.registry import deps

def _restored_media(snapshot: dict[str, Any]) -> dict[str, Path]:
    media_roots = {"media": deps.MEDIA_ROOT, "global-media": deps.GLOBAL_MEDIA_ROOT}
    if snapshot.get("scope") == "characters":
        return media_roots
    return {"media": deps.MEDIA_ROOT} if snapshot.get("includeMedia") else {}


def _media_references(value: Any, prefix: str) -> set[str]:
    references: set[str] = set()
    if isinstance(value, dict):
        for child in value.values():
            references.update(_media_references(child, prefix))
    elif isinstance(value, list):
        for child in value:
            references.update(_media_references(child, prefix))
    elif isinstance(value, str) and value.startswith(prefix):
        references.add(value.removeprefix(prefix))
    return references


def _validate_staged_media(snapshot: dict[str, Any], staging: Path) -> None:
    if snapshot.get("scope") == "characters":
        checks = [
            ("project.json", "media/characters", "/media/characters/"),
            ("global-characters.json", "global-media/characters", "/global-media/characters/"),
        ]
    else:
        checks = [("project.json", "media", "/media/")]
    restored_media = _restored_media(snapshot)
    for metadata_name, media_name, prefix in checks:
        media_boundary = media_name.split("/", 1)[0]
        if media_boundary not in restored_media:
            continue
        metadata = staging / metadata_name
        if not metadata.is_file():
            continue
        try:
            value = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=409, detail="履歴の保存データが壊れているため復元できません。") from error
        media_root = (staging / media_name).resolve()
        for relative in _media_references(value, prefix):
            media_targets = snapshot.get("mediaTargets") if media_boundary == "media" else None
            if media_targets and not any(
                relative == target or relative.startswith(f"{target}/") for target in media_targets
            ):
                continue
            candidate = (media_root / relative).resolve()
            try:
                candidate.relative_to(media_root)
            except ValueError as error:
                raise HTTPException(status_code=409, detail="履歴の媒体参照が不正なため復元できません。") from error
            if not candidate.is_file():
                raise HTTPException(
                    status_code=409,
                    detail="画像または音声を欠いた履歴は安全に復元できません。",
                )


def _restore_media_files(staging: Path, restored_media: dict[str, Path]) -> None:
    """Restore known preimages without deleting files absent from a snapshot."""
    for name, destination in restored_media.items():
        replacement = staging / name
        if not replacement.exists():
            continue
        for source in replacement.rglob("*"):
            if not source.is_file():
                continue
            target = destination / source.relative_to(replacement)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.undo-{uuid4().hex}.tmp")
            try:
                shutil.copy2(source, temporary)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)


def _remove_displaced_media(paths: set[str], restored_media: dict[str, Path]) -> None:
    """Delete only files proven to belong to the verified live boundary."""
    for name, destination in restored_media.items():
        prefix = f"{name}/"
        root = destination.resolve()
        for path in paths:
            if not path.startswith(prefix):
                continue
            target = (root / path.removeprefix(prefix)).resolve()
            try:
                target.relative_to(root)
            except ValueError as error:
                raise HTTPException(status_code=409, detail="履歴の媒体参照が不正なため復元できません。") from error
            target.unlink(missing_ok=True)

from __future__ import annotations

from binascii import Error as BinasciiError

from server.app_deps import shutil, time, b64decode, Any, HTTPException
from server.registry import deps


def decode_avatar_image(value: str, *, label: str, max_bytes: int, thumbnail: bool = False) -> tuple[bytes, str]:
    encoded = value.split(",", 1)[-1]
    try:
        image = b64decode(encoded, validate=True)
    except (BinasciiError, ValueError) as error:
        raise HTTPException(status_code=422, detail=f"The {label} was not valid base64 data.") from error
    if len(image) > max_bytes:
        raise HTTPException(status_code=413, detail=f"{label.capitalize()} is too large.")
    signatures = ((b"\x89PNG\r\n\x1a\n", ".png"), (b"\xff\xd8\xff", ".jpg"))
    extension = next((suffix for signature, suffix in signatures if image.startswith(signature)), None)
    if extension is None and image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        extension = ".webp"
    if extension is None:
        raise HTTPException(status_code=422, detail=f"{label.capitalize()} must be a PNG, JPEG, or WebP image.")
    if thumbnail and extension != ".png":
        raise HTTPException(status_code=422, detail="Thumbnail must be a PNG created by the cropper.")
    return image, extension


def avatar_directory(character_id: str, update_global: bool):
    root = deps.GLOBAL_MEDIA_ROOT if update_global else deps.MEDIA_ROOT
    return root / "characters" / deps.safe_segment(character_id)


def avatar_files(directory):
    return [directory / name for name in (
        "avatar.png", "avatar-thumbnail.png", "avatar-original.png", "avatar-original.jpg",
        "avatar-original.jpeg", "avatar-original.webp",
    )]


@deps.app.put("/api/characters/{character_id}/avatar")
def update_character_avatar(character_id: str, request: deps.UpdateCharacterAvatarRequest) -> dict[str, Any]:
    original, extension = decode_avatar_image(request.original_image_base64, label="avatar image", max_bytes=8 * 1024 * 1024)
    thumbnail, _ = decode_avatar_image(request.thumbnail_image_base64, label="avatar thumbnail", max_bytes=1024 * 1024, thumbnail=True)
    project = deps.read_project()
    character = deps.find_character(project, character_id)
    update_global = character.get("scope") == "global" or deps.project_character_matches_global(character)
    directory = avatar_directory(character_id, update_global)
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / f".avatar-rollback-{deps.new_id('avatar')}"
    original_target, thumbnail_target = directory / f"avatar-original{extension}", directory / "avatar-thumbnail.png"
    replacement_started = False
    committed = False
    rollback_failed = False
    try:
        backup.mkdir()
        for old_file in avatar_files(directory):
            if old_file.is_file():
                old_file.replace(backup / old_file.name)
        replacement_started = True
        original_target.write_bytes(original)
        thumbnail_target.write_bytes(thumbnail)
        media_url = deps.global_media_url if update_global else deps.media_url
        character.update({"avatarOriginalUrl": media_url(original_target), "avatarThumbnailUrl": media_url(thumbnail_target), "avatarUrl": media_url(thumbnail_target), "avatarVersion": time.time_ns()})
        if update_global:
            updated = []
            for item in deps.read_global_characters():
                next_item = dict(item)
                if item.get("id") == character_id:
                    next_item.update({key: character[key] for key in ("avatarOriginalUrl", "avatarThumbnailUrl", "avatarUrl", "avatarVersion")})
                updated.append(next_item)
            deps.write_global_characters(updated)
        else:
            deps.write_project(project)
        committed = True
    except Exception:
        if replacement_started:
            for installed in avatar_files(directory):
                try:
                    installed.unlink(missing_ok=True)
                except OSError:
                    rollback_failed = True
        if backup.is_dir():
            for previous in backup.iterdir():
                try:
                    previous.replace(directory / previous.name)
                except OSError:
                    rollback_failed = True
        raise
    finally:
        if committed or not rollback_failed:
            shutil.rmtree(backup, ignore_errors=True)
    return character


@deps.app.delete("/api/characters/{character_id}/avatar")
def delete_character_avatar(character_id: str) -> dict[str, Any]:
    project = deps.read_project()
    character = deps.find_character(project, character_id)
    update_global = character.get("scope") == "global" or deps.project_character_matches_global(character)
    directory = avatar_directory(character_id, update_global)
    avatar_keys = ("avatarOriginalUrl", "avatarThumbnailUrl", "avatarUrl", "avatarVersion")
    for key in avatar_keys:
        character.pop(key, None)
    if update_global:
        updated = []
        for item in deps.read_global_characters():
            next_item = dict(item)
            if item.get("id") == character_id:
                for key in avatar_keys:
                    next_item.pop(key, None)
            updated.append(next_item)
        deps.write_global_characters(updated)
    else:
        deps.write_project(project)
    for avatar in avatar_files(directory):
        try:
            avatar.unlink(missing_ok=True)
        except OSError:
            pass
    return character


deps.register(__name__, ["decode_avatar_image", "delete_character_avatar", "update_character_avatar"])

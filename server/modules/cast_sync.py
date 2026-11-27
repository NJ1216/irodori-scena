from __future__ import annotations

from server.app_deps import shutil, Path, Any, HTTPException
from server.registry import deps
from server.modules.cast_identity import matches_global_candidates
from server.modules.project_repository import cast_mutation


def _avatar_digest(character: dict[str, Any], key: str, *, prefix: str, root: Path) -> str | None:
    value = character.get(key)
    if key == "avatarThumbnailUrl":
        value = value or character.get("avatarUrl")
    url = str(value or "")
    if not url:
        return ""
    if not url.startswith(prefix):
        return None
    path = (root / url.removeprefix(prefix)).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return deps.audio_digest(path)
    except OSError:
        return None


def _matches_global_snapshot(character: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    for candidate in candidates:
        if not matches_global_candidates(character, [candidate]):
            continue
        if all(
            _avatar_digest(character, key, prefix="/media/", root=deps.MEDIA_ROOT)
            == _avatar_digest(candidate, key, prefix="/global-media/", root=deps.GLOBAL_MEDIA_ROOT)
            for key in ("avatarOriginalUrl", "avatarThumbnailUrl")
        ):
            return True
    return False


def global_cast_update_candidates(project: dict[str, Any]) -> list[dict[str, str]]:
    global_characters: dict[str, list[dict[str, Any]]] = {}
    for character in deps.read_global_characters():
        global_characters.setdefault(str(character.get("id", "")), []).append(character)
    candidates: list[dict[str, str]] = []
    for character in project.get("characters", []):
        if not isinstance(character, dict) or character.get("scope") == "global":
            continue
        character_id = str(character.get("id", ""))
        matches = global_characters.get(character_id, [])
        if matches and not _matches_global_snapshot(character, matches):
            candidates.append({"id": character_id, "name": str(matches[-1].get("name", ""))})
    return candidates


def global_avatar_source(source_url: str, *, character_name: str) -> Path | None:
    if not source_url:
        return None
    if not source_url.startswith("/global-media/"):
        raise HTTPException(status_code=422, detail=f"グローバルキャスト「{character_name}」の画像参照が不正です。")
    source = (deps.GLOBAL_MEDIA_ROOT / source_url.removeprefix("/global-media/")).resolve()
    try:
        source.relative_to(deps.GLOBAL_MEDIA_ROOT.resolve())
    except ValueError as error:
        raise HTTPException(
            status_code=422, detail=f"グローバルキャスト「{character_name}」の画像参照が不正です。"
        ) from error
    if not source.is_file():
        raise HTTPException(
            status_code=422,
            detail=f"グローバルキャスト「{character_name}」の画像ファイルが見つかりません。",
        )
    return source


def copy_global_avatar(source: Path | None, target: Path) -> Path | None:
    if source is None:
        return None
    shutil.copy2(source, target)
    return target


def project_snapshot_from_global(character: dict[str, Any]) -> dict[str, Any]:
    character_id = str(character.get("id", ""))
    character_name = str(character.get("name", ""))
    source = Path(str(character.get("referenceFile", ""))).resolve()
    if not source.is_file():
        raise HTTPException(status_code=422, detail=f"Global character {character_name} has no reference WAV.")
    original_url = str(character.get("avatarOriginalUrl", ""))
    thumbnail_url = str(character.get("avatarThumbnailUrl") or character.get("avatarUrl", ""))
    original_source = global_avatar_source(original_url, character_name=character_name)
    thumbnail_source = global_avatar_source(thumbnail_url, character_name=character_name)
    target = deps.MEDIA_ROOT / "characters" / deps.safe_segment(character_id) / "reference.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    snapshot = dict(character)
    snapshot.update(
        {
            "scope": "project",
            "referenceAudioUrl": deps.media_url(target),
            "referenceFile": str(target),
            "audioHash": deps.audio_digest(target),
        }
    )
    for key in ("avatarOriginalUrl", "avatarThumbnailUrl", "avatarUrl"):
        snapshot.pop(key, None)
    suffix = Path(original_url).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
        suffix = ".png"
    original = copy_global_avatar(original_source, target.with_name(f"avatar-original{suffix}"))
    if original:
        snapshot["avatarOriginalUrl"] = deps.media_url(original)
    thumbnail = copy_global_avatar(thumbnail_source, target.with_name("avatar-thumbnail.png"))
    if thumbnail:
        thumbnail_url = deps.media_url(thumbnail)
        snapshot["avatarThumbnailUrl"] = thumbnail_url
        snapshot["avatarUrl"] = thumbnail_url
    return snapshot


@cast_mutation
def apply_global_cast_updates(character_ids: list[str]) -> dict[str, Any]:
    project = deps.read_project()
    global_characters = {str(character.get("id", "")): character for character in deps.read_global_characters()}
    requested = set(character_ids)
    project["characters"] = [
        project_snapshot_from_global(global_characters[str(character.get("id", ""))])
        if isinstance(character, dict)
        and str(character.get("id", "")) in requested
        and str(character.get("id", "")) in global_characters
        else character
        for character in project.get("characters", [])
    ]
    deps.write_project(project)
    return deps.read_project()


deps.register(
    __name__,
    [
        "apply_global_cast_updates",
        "global_cast_update_candidates",
        "project_snapshot_from_global",
    ],
)

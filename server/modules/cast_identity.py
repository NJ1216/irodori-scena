from __future__ import annotations

from server.app_deps import hashlib, json, Path, Any
from server.registry import deps


def character_identity(character: dict[str, Any]) -> tuple[str, str]:
    character_id = str(character.get("id", ""))
    audio_hash = str(character.get("audioHash", ""))
    if not audio_hash:
        reference = Path(str(character.get("referenceFile", "")))
        if reference.is_file():
            try:
                audio_hash = deps.audio_digest(reference)
            except OSError:
                audio_hash = ""
    return (character_id, audio_hash)


def character_content_fingerprint(character: dict[str, Any]) -> str:
    """Compare editable cast content without workspace-specific media paths."""
    content = {
        "id": str(character.get("id", "")),
        "name": str(character.get("name", "")),
        "profile": str(character.get("profile", "")),
        "profileDetails": deps.normalize_character_profile_details(character.get("profileDetails")),
        "voiceKeywords": str(character.get("voiceKeywords", "")),
        "lora": character.get("lora"),
        "loraMix": character.get("loraMix"),
        "sampleText": character.get("sampleText"),
        "imagePrompt": str(character.get("imagePrompt", "")),
        "imagePromptPreferences": character.get("imagePromptPreferences", {}),
        "audioHash": character_identity(character)[1],
        "avatarVersion": character.get("avatarVersion"),
    }
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def matches_global_candidates(character: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
    """Match any same-ID entry, including libraries containing duplicate IDs."""
    character_id = str(character.get("id", ""))
    if not character_id:
        return False
    return any(
        str(global_character.get("id", "")) == character_id
        and character_content_fingerprint(character) == character_content_fingerprint(global_character)
        for global_character in candidates
    )


deps.register(__name__, ["character_identity", "character_content_fingerprint"])

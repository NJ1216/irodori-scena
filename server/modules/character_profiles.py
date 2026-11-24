from __future__ import annotations

from server.app_deps import json, re, Path, Any, HTTPException
from server.registry import deps


def safe_segment(value: str) -> str:
    return re.sub("[^a-zA-Z0-9_-]", "_", value)


def safe_download_name(value: str, fallback: str) -> str:
    """Keep Japanese titles intact while removing only unsafe filename characters."""
    name = re.sub("[\\\\/:\\x00-\\x1f]", "_", value).strip(". ")
    return name or fallback


CHARACTER_PROFILE_TEXT_LIMITS = {
    "familyName": 80,
    "familyNameKana": 80,
    "givenName": 80,
    "givenNameKana": 80,
    "age": 80,
    "bloodType": 40,
    "birthDate": 80,
    "birthplace": 160,
    "residence": 160,
    "gender": 80,
    "role": 160,
    "defaultAddressBasis": 40,
    "defaultHonorific": 80,
    "defaultAddressNote": 600,
    "skills": 1000,
    "hobbies": 1000,
    "likes": 1000,
    "dislikes": 1000,
    "personality": 1000,
    "speechStyle": 1000,
    "background": 1600,
    "otherRelationships": 1200,
}

CHARACTER_PROFILE_LIST_FIELDS = {"aliases", "firstPerson", "secondPerson"}


def normalize_birthday_value(value: str) -> str:
    """Keep birthdays as month and day only, never a birth year."""
    text = re.sub("\\s+", "", value)
    japanese = re.search("(?:\\d{1,4}年)?(\\d{1,2})月(\\d{1,2})日", text)
    if japanese:
        return f"{int(japanese.group(1))}月{int(japanese.group(2))}日"
    numeric = re.search("(?:\\d{1,4}[./-])?(\\d{1,2})[./-](\\d{1,2})", text)
    if numeric:
        return f"{int(numeric.group(1))}月{int(numeric.group(2))}日"
    return text


def katakana_to_hiragana(value: str) -> str:
    return "".join((chr(ord(character) - 96) if "ァ" <= character <= "ヶ" else character for character in value))


def profile_text_value(value: object) -> str:
    """Render model-returned lists as a friendly Japanese comma-separated value."""
    if isinstance(value, list):
        return "、".join((str(item).strip() for item in value if str(item).strip()))
    text = str(value or "").strip()
    if not (text.startswith("[") and text.endswith("]")):
        return text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = re.findall("['\\\"]([^'\\\"]+)['\\\"]", text)
    if isinstance(parsed, list):
        values = [str(item).strip() for item in parsed if str(item).strip()]
        if values:
            return "、".join(values)
    return text


def normalized_cast_relations(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}
    relations: dict[str, dict[str, str]] = {}
    for character_id, raw_relation in value.items():
        key = str(character_id).strip()[:120]
        source = {"relationship": raw_relation} if isinstance(raw_relation, str) else raw_relation
        if not key or not isinstance(source, dict):
            continue
        address = str(source.get("address", "")).strip()[:160]
        relationship = str(source.get("relationship", source.get("note", ""))).strip()[:1200]
        normalized = {}
        if address:
            normalized["address"] = address
        if relationship:
            normalized["relationship"] = relationship
        if normalized:
            relations[key] = normalized
    return relations


def normalize_character_profile_details(value: object) -> dict[str, Any]:
    """Keep a compact, predictable character sheet for projects and prompts."""
    source = value if isinstance(value, dict) else {}
    migrated = dict(source)
    honorifics = [profile_text_value(source.get(key, "")) for key in (
        "defaultHonorificFemale", "defaultHonorificMale", "defaultHonorificOther"
    )]
    honorifics = list(dict.fromkeys(item for item in honorifics if item))
    if not profile_text_value(migrated.get("defaultHonorific", "")) and honorifics:
        migrated["defaultHonorific"] = "／".join(honorifics)
    legacy_second = profile_text_value(source.get("defaultSecondPerson", ""))
    if legacy_second:
        current = source.get("secondPerson", [])
        migrated["secondPerson"] = [*(current if isinstance(current, list) else [current]), legacy_second]
    legacy_register = profile_text_value(source.get("defaultSpeechRegister", ""))
    if legacy_register and legacy_register not in profile_text_value(source.get("speechStyle", "")):
        migrated["speechStyle"] = "。".join(filter(None, [legacy_register, profile_text_value(source.get("speechStyle", ""))]))
    migrated.setdefault("likes", profile_text_value(source.get("favoriteFoods", "")))
    migrated.setdefault("dislikes", profile_text_value(source.get("dislikedFoods", "")))
    legacy_preferences = profile_text_value(source.get("likesDislikes", ""))
    if legacy_preferences:
        migrated["likes"] = "\n".join(filter(None, [profile_text_value(migrated.get("likes", "")), legacy_preferences]))
    migrated.setdefault("otherRelationships", profile_text_value(source.get("relationships", "")))
    details: dict[str, Any] = {}
    for field, limit in CHARACTER_PROFILE_TEXT_LIMITS.items():
        text = profile_text_value(migrated.get(field, ""))
        if field == "birthDate":
            text = normalize_birthday_value(text)
        if field in {"familyNameKana", "givenNameKana"}:
            text = katakana_to_hiragana(text)
        if text:
            details[field] = text[:limit]
    for field in CHARACTER_PROFILE_LIST_FIELDS:
        raw = migrated.get(field, [])
        items = raw if isinstance(raw, list) else re.split("[、,，\\n]", str(raw))
        cleaned = [str(item).strip()[:80] for item in items if str(item).strip()]
        if cleaned:
            details[field] = list(dict.fromkeys(cleaned))[:8]
    relations = normalized_cast_relations(source.get("castRelations", {}))
    if relations:
        details["castRelations"] = relations
    return details


def normalize_character_profile(character: object) -> dict[str, Any]:
    """Migrate one saved cast sheet without discarding its legacy free memo."""
    source = character if isinstance(character, dict) else {}
    normalized = dict(source)
    raw_details = source.get("profileDetails")
    legacy_notes = profile_text_value(raw_details.get("notes", "")) if isinstance(raw_details, dict) else ""
    free_profile = profile_text_value(source.get("profile", ""))
    if legacy_notes and legacy_notes not in free_profile:
        normalized["profile"] = "\n".join(filter(None, [free_profile, legacy_notes]))
    normalized["profileDetails"] = normalize_character_profile_details(raw_details)
    return normalized


def character_llm_profile(character: dict[str, Any]) -> str:
    """Turn the editable character sheet into concise, labelled LLM context."""
    details = normalize_character_profile_details(character.get("profileDetails"))
    labels = {
        "familyName": "苗字",
        "familyNameKana": "苗字のふりがな",
        "givenName": "名前",
        "givenNameKana": "名前のふりがな",
        "aliases": "愛称",
        "age": "年齢",
        "bloodType": "血液型",
        "birthDate": "誕生日",
        "birthplace": "出身地",
        "residence": "居住地",
        "gender": "性別",
        "role": "職業",
        "firstPerson": "一人称",
        "secondPerson": "二人称",
        "defaultAddressBasis": "通常の呼び方",
        "defaultHonorific": "基本の敬称",
        "defaultAddressNote": "通常の呼び方の補足",
        "skills": "特技",
        "hobbies": "趣味",
        "likes": "好きなもの",
        "dislikes": "苦手なもの",
        "personality": "性格",
        "speechStyle": "話し方",
        "background": "背景",
        "otherRelationships": "その他の人間関係",
    }
    parts = []
    for field in (
        "familyName",
        "familyNameKana",
        "givenName",
        "givenNameKana",
        "aliases",
        "age",
        "bloodType",
        "birthDate",
        "birthplace",
        "residence",
        "gender",
        "role",
        "firstPerson",
        "secondPerson",
        "defaultAddressBasis",
        "defaultHonorific",
        "defaultAddressNote",
        "skills",
        "hobbies",
        "likes",
        "dislikes",
        "personality",
        "speechStyle",
        "background",
        "otherRelationships",
    ):
        value = details.get(field)
        if isinstance(value, list):
            value = "／".join(value)
        if value:
            parts.append(f"{labels[field]}: {value}")
    free_profile = str(character.get("profile", "")).strip()
    if free_profile:
        parts.append(f"自由メモ: {free_profile}")
    return "\n".join(parts) or "（設定なし）"


def character_relation_reference(character: dict[str, Any]) -> dict[str, str]:
    """Keep only relationship-relevant context for profile suggestions."""
    details = normalize_character_profile_details(character.get("profileDetails"))
    fields = (
        ("role", "役割", 120),
        ("personality", "性格", 220),
        ("speechStyle", "話し方", 160),
        ("background", "背景", 260),
    )
    reference = {
        label: str(details.get(field, "")).strip()[:limit]
        for field, label, limit in fields
        if str(details.get(field, "")).strip()
    }
    free_memo = str(character.get("profile", "")).strip()
    if free_memo:
        reference["自由メモ"] = free_memo[:260]
    return reference or {"概要": "（設定なし）"}


DRAFT_PROFILE_LABELS = {
    "familyName": "苗字",
    "familyNameKana": "苗字のふりがな",
    "givenName": "名前",
    "givenNameKana": "名前のふりがな",
    "aliases": "愛称",
    "age": "年齢",
    "bloodType": "血液型",
    "birthDate": "誕生日",
    "birthplace": "出身地",
    "residence": "居住地",
    "gender": "性別",
    "role": "職業",
    "firstPerson": "一人称",
    "secondPerson": "二人称",
    "defaultAddressBasis": "通常の呼び方",
    "defaultHonorific": "基本の敬称",
    "defaultAddressNote": "通常の呼び方の補足",
    "skills": "特技",
    "hobbies": "趣味",
    "likes": "好きなもの",
    "dislikes": "苦手なもの",
    "personality": "性格",
    "speechStyle": "話し方",
    "background": "背景",
    "otherRelationships": "その他の人間関係",
    "freeProfile": "自由メモ",
}

DRAFT_CORE_PROFILE_FIELDS = (
    "familyName",
    "familyNameKana",
    "givenName",
    "givenNameKana",
    "aliases",
    "age",
    "gender",
    "role",
    "firstPerson",
    "secondPerson",
    "defaultAddressBasis",
    "defaultHonorific",
    "defaultAddressNote",
    "personality",
    "speechStyle",
)

DRAFT_OPTIONAL_PROFILE_FIELDS = frozenset(
    {
        "bloodType",
        "birthDate",
        "birthplace",
        "residence",
        "skills",
        "hobbies",
        "likes",
        "dislikes",
        "background",
        "otherRelationships",
        "freeProfile",
    }
)


def character_record(
    *, character_id: str, name: str, profile: str, voice_keywords: str, reference: Path, scope: str = "project"
) -> dict[str, Any]:
    return {
        "id": character_id,
        "name": name.strip(),
        "profile": profile.strip(),
        "profileDetails": {},
        "voiceKeywords": voice_keywords,
        "imagePromptPreferences": {},
        "referenceAudioUrl": global_media_url(reference) if scope == "global" else media_url(reference),
        "referenceFile": str(reference),
        "audioHash": deps.audio_digest(reference),
        "scope": scope,
        "createdAt": deps.now_ms(),
    }


def media_url(path: Path) -> str:
    try:
        return "/media/" + path.resolve().relative_to(deps.MEDIA_ROOT.resolve()).as_posix()
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Generated media escaped the SCENA data directory.") from error


def global_media_url(path: Path) -> str:
    try:
        return "/global-media/" + path.resolve().relative_to(deps.GLOBAL_MEDIA_ROOT.resolve()).as_posix()
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Global character media escaped the library directory.") from error


deps.register(
    __name__,
    [
        "CHARACTER_PROFILE_LIST_FIELDS",
        "CHARACTER_PROFILE_TEXT_LIMITS",
        "DRAFT_CORE_PROFILE_FIELDS",
        "DRAFT_OPTIONAL_PROFILE_FIELDS",
        "DRAFT_PROFILE_LABELS",
        "character_llm_profile",
        "character_relation_reference",
        "character_record",
        "global_media_url",
        "katakana_to_hiragana",
        "media_url",
        "normalize_birthday_value",
        "normalize_character_profile",
        "normalize_character_profile_details",
        "profile_text_value",
        "safe_download_name",
        "safe_segment",
    ],
)

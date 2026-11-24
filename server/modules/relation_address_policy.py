from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from server.registry import deps


STANDARD_HONORIFICS = ("", "さん", "ちゃん", "くん", "君", "様", "殿", "氏")
SETTING_BASIS = frozenset({"formal_title", "relational_nickname"})
NORMALIZED_ADDRESSES = {
    "あなたさん": "あなた", "貴方さん": "貴方", "君さん": "君", "きみさん": "きみ",
    "あなたちゃん": "あなた", "貴方ちゃん": "貴方", "あなたくん": "あなた",
    "貴方くん": "貴方", "あなた君": "あなた", "貴方君": "貴方",
}
DISALLOWED_AI_ADDRESSES = frozenset({
    "あんた様", "お前様", "てめえさん", "てめえ様", "貴様さん", "貴様様",
})
STACKED_HONORIFIC_ENDINGS = ("さん様", "様さん", "ちゃんさん", "くんさん", "君さん", "様様")
MAX_ADDRESS_LENGTH = 40


@dataclass(frozen=True)
class AddressCandidate:
    id: str
    value: str
    kind: str


def normalize_known_address(value: str) -> tuple[str | None, str | None]:
    cleaned = value.strip()
    compact = re.sub(r"\s+", "", cleaned)
    if compact in NORMALIZED_ADDRESSES:
        return NORMALIZED_ADDRESSES[compact], "known_unnatural_combination"
    if not cleaned:
        return None, "empty"
    if "|" in value or any(character in "\n\r" or ord(character) < 32 for character in value):
        return None, "control_or_protocol_character"
    if len(cleaned) > MAX_ADDRESS_LENGTH:
        return None, "too_long"
    if compact in DISALLOWED_AI_ADDRESSES or compact.endswith(STACKED_HONORIFIC_ENDINGS):
        return None, "disallowed_or_stacked_honorific"
    return cleaned, None


def accepted_ai_relation_value(field: str, value: str) -> str | None:
    """Compatibility validator; profile suggestions use the candidate resolver below."""
    if field != "address":
        return value.strip() or None
    accepted, reason = normalize_known_address(value)
    return None if reason == "known_unnatural_combination" else accepted


def address_candidates(target: dict[str, Any], subject_core: dict[str, Any]) -> list[AddressCandidate]:
    details = deps.normalize_character_profile_details(target.get("profile_details"))
    raw: list[tuple[str, str]] = []
    for key in ("familyName", "givenName"):
        if value := str(details.get(key, "")).strip():
            raw.append(("name", value))
    if value := str(target.get("name", "")).strip():
        raw.append(("name", value))
    aliases = details.get("aliases", [])
    if isinstance(aliases, list):
        raw.extend(("alias", str(value).strip()) for value in aliases if str(value).strip())
    second_person = subject_core.get("secondPerson", [])
    if isinstance(second_person, list):
        raw.extend(("pronoun", str(value).strip()) for value in second_person if str(value).strip())
    result: list[AddressCandidate] = []
    seen: set[str] = set()
    for kind, value in raw:
        if value in seen or normalize_known_address(value)[0] is None:
            continue
        seen.add(value)
        result.append(AddressCandidate(f"c{len(result) + 1}", value, kind))
    return result


def allowed_honorifics(subject_core: dict[str, Any]) -> dict[str, str]:
    values = list(STANDARD_HONORIFICS)
    custom = str(subject_core.get("defaultHonorific", "")).strip()
    if custom and custom not in values and normalize_known_address(custom)[0] == custom and len(custom) <= 8:
        values.append(custom)
    return {"h0" if not value else f"h{index}": value for index, value in enumerate(values)}


def resolve_candidate_address(*, candidate_id: str, honorific_id: str, basis: str,
                              candidates: list[AddressCandidate], honorifics: dict[str, str]) -> tuple[str | None, str | None]:
    candidate = next((item for item in candidates if item.id == candidate_id), None)
    if candidate is None:
        return None, "unknown_candidate_id"
    honorific = honorifics.get(honorific_id)
    if honorific is None:
        return None, "unknown_honorific_id"
    if basis != candidate.kind:
        return None, "invalid_basis"
    return normalize_known_address(candidate.value + honorific)


def resolve_custom_address(value: str, honorific_id: str, basis: str,
                           honorifics: dict[str, str]) -> tuple[str | None, str | None]:
    if basis not in SETTING_BASIS:
        return None, "setting_basis_required"
    honorific = honorifics.get(honorific_id)
    if honorific is None:
        return None, "unknown_honorific_id"
    return normalize_known_address(value.strip() + honorific)


deps.register(__name__, [
    "accepted_ai_relation_value", "address_candidates", "allowed_honorifics",
    "normalize_known_address", "resolve_candidate_address", "resolve_custom_address",
])

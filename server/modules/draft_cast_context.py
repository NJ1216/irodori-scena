"""Cast aliases and LLM-facing cast context for draft generation."""

from __future__ import annotations

from server.app_deps import Any
from server.registry import deps
from server.modules.character_profiles import (
    DRAFT_CORE_PROFILE_FIELDS,
    DRAFT_OPTIONAL_PROFILE_FIELDS,
    DRAFT_PROFILE_LABELS,
    normalize_character_profile_details,
)


def draft_character_profile(character: dict[str, Any], optional_fields: set[str] | None = None) -> str:
    """Compile only dialogue-critical fields plus optional theme-relevant facts."""
    details = normalize_character_profile_details(character.get("profileDetails"))
    fields = (*DRAFT_CORE_PROFILE_FIELDS, *sorted(optional_fields or set()))
    parts: list[str] = []
    for field in fields:
        value: Any = character.get("profile", "") if field == "freeProfile" else details.get(field)
        if isinstance(value, list):
            value = "／".join((str(item).strip() for item in value if str(item).strip()))
        value = str(value or "").strip()
        if value:
            parts.append(f"{DRAFT_PROFILE_LABELS[field]}: {value}")
    return "\n".join(parts) or "（設定なし）"


def draft_cast_alias(number: int) -> str:
    """Return a short spreadsheet-style alias: A..Z, AA..AZ, BA..."""
    value = max(0, number)
    result = ""
    while True:
        value, remainder = divmod(value, 26)
        result = chr(ord("A") + remainder) + result
        if value == 0:
            return result
        value -= 1


def draft_cast_aliases(characters: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(character.get("id", "")).strip(): draft_cast_alias(index)
        for index, character in enumerate(characters)
        if str(character.get("id", "")).strip()
    }


def draft_context_inventory(characters: list[dict[str, Any]], cast_alias_by_id: dict[str, str]) -> list[dict[str, Any]]:
    """Describe optional facts with bounded values and no persistent IDs."""
    inventory: list[dict[str, Any]] = []
    for character in characters:
        details = normalize_character_profile_details(character.get("profileDetails"))
        available: list[dict[str, str]] = []
        for field in sorted(DRAFT_OPTIONAL_PROFILE_FIELDS):
            value = character.get("profile", "") if field == "freeProfile" else details.get(field)
            if value:
                rendered = "／".join(value) if isinstance(value, list) else str(value)
                available.append({
                    "field": field,
                    "label": DRAFT_PROFILE_LABELS[field],
                    "value": rendered.strip()[:240],
                })
        inventory.append(
            {
                "cast": cast_alias_by_id.get(str(character.get("id", "")), "?"),
                "name": str(character.get("name", "")),
                "available_optional_fields": available,
            }
        )
    return inventory


def draft_cast_context(
    characters: list[dict[str, Any]],
    *,
    cast_alias_by_id: dict[str, str],
    request: deps.DraftRequest | None = None,
    optional_fields_by_cast: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Compile the selected cast sheets into deterministic draft context.

    Character sheets are small, exact constraints (especially pronouns and
    forms of address), so they must not depend on a similarity search.  Keep
    individual relationship notes separate and resolve their target IDs to
    display names before giving them to the LLM.
    """
    selected = {
        str(character.get("id", "")).strip(): character
        for character in characters
        if str(character.get("id", "")).strip()
    }
    context: list[dict[str, Any]] = []
    for character_id, character in selected.items():
        settings = request.cast_settings.get(character_id) if request else None
        appearance_priority = settings.appearance_priority if settings else "standard"
        details = normalize_character_profile_details(character.get("profileDetails"))
        relations = details.get("castRelations", {})
        relationship_rules: list[dict[str, str]] = []
        if isinstance(relations, dict):
            for target_id, relation in relations.items():
                target = selected.get(str(target_id))
                if not target or str(target_id) == character_id or (not isinstance(relation, dict)):
                    continue
                address = str(relation.get("address", "")).strip()
                relationship = str(relation.get("relationship", "")).strip()
                if address or relationship:
                    relationship_rules.append(
                        {
                            "target": cast_alias_by_id.get(str(target_id), "?"),
                            "name": str(target.get("name", "")).strip() or "（名前未設定）",
                            "address": address,
                            "relationship": relationship,
                        }
                    )
        context.append(
            {
                "cast": cast_alias_by_id.get(character_id, "?"),
                "name": str(character.get("name", "")).strip() or "（名前未設定）",
                "profile": draft_character_profile(character, (optional_fields_by_cast or {}).get(character_id, set())),
                "reader_facing_introduction_seed": deps.draft_reader_introduction(character),
                "relations": relationship_rules,
                "preferences": {
                    "emoji": "許可"
                    if settings and settings.emoji_expressions
                    else "禁止",
                    "fillers": "多めに自然に入れる"
                    if settings and settings.filler_richness
                    else "必要な箇所だけにする",
                    "priority": appearance_priority,
                },
            }
        )
    return context


deps.register(
    __name__,
    [
        "draft_character_profile",
        "draft_cast_alias",
        "draft_cast_aliases",
        "draft_context_inventory",
        "draft_cast_context",
    ],
)

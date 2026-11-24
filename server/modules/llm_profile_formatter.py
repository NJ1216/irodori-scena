"""Deterministic recovery for character-profile suggestions."""

from __future__ import annotations

from server.app_deps import json, re
from server.modules.llm_response_formatters import _lines, _text
from server.registry import deps


def _profile_records(raw: object) -> list[list[str]] | None:
    records: list[list[str]] = []
    for line in _lines(raw):
        parts = [part.strip() for part in line.split("|")]
        while parts and not parts[-1]:
            parts.pop()
        if not parts:
            continue
        if parts[0] not in {"FIELD", "RELATION"}:
            # Some models drop only the FIELD marker while retaining an
            # unambiguous field key/label and value.
            parts.insert(0, "FIELD")
        current: list[str] = []
        for part in parts:
            if part in {"FIELD", "RELATION"} and current:
                records.append(current)
                current = [part]
            else:
                current.append(part)
        records.append(current)
    return records or None


def _normalized_profile_separators(value: str) -> str:
    normalized = re.sub(r"\s*[／/・,，]+\s*", "、", value)
    return re.sub("、{2,}", "、", normalized).strip("、")


def _profile_value(field: str, value: str) -> object:
    if field not in deps.CHARACTER_PROFILE_LIST_FIELDS:
        return value.strip().rstrip("|／/").rstrip()
    normalized = _normalized_profile_separators(value)
    # `名前＋さん` and `苗字＋君` describe a calling rule, not an actual
    # first- or second-person word.  They are unusable as a pronoun option.
    return [item for item in normalized.split("、") if item and "+" not in item and "＋" not in item]


def _standard_profile_field(
    label: str, *, label_to_field: dict[str, str], blank_fields: set[str], details: dict[str, object]
) -> str | None:
    label_aliases = {
        "背景": "background",
        "好き嫌い": "likesDislikes",
        "好きな物・苦手な物": "likesDislikes",
        "好きな物／苦手な物": "likesDislikes",
        "女性の敬称": "defaultHonorificFemale",
        "男性の敬称": "defaultHonorificMale",
        "その他への敬称": "defaultHonorificOther",
        "その他の敬称": "defaultHonorificOther",
        "口調": "speechStyle",
        "基本の話し方": "speechStyle",
        "話し方の特徴": "speechStyle",
        "話し方・口調": "speechStyle",
        "呼称の基準": "defaultAddressBasis",
        "呼称の補足": "defaultAddressNote",
    }
    field = label_to_field.get(label, label_aliases.get(label, label if label in blank_fields else None))
    # Some models use 「話し方」 for both the register and the concrete speech
    # style.  Those are the only two fixed fields with this recoverable order.
    if label == "話し方" and field in details and "speechStyle" in blank_fields and "speechStyle" not in details:
        return "speechStyle"
    return field


def _is_unspecified_profile_value(value: str) -> bool:
    return value.strip() in {"未設定", "不明", "該当なし", "なし", "N/A"}

def _packed_profile_fields(
    parts: list[str], *, labels: dict[str, str], blank_fields: set[str]
) -> dict[str, object] | None:
    if len(parts) < 4 or parts[2] not in labels:
        return None
    details: dict[str, object] = {}
    payload = parts[2:]
    index = 0
    while index < len(payload):
        field = payload[index]
        if field not in labels or field not in blank_fields or field in details:
            return None
        index += 1
        value_parts: list[str] = []
        while index < len(payload) and payload[index] not in labels:
            value_parts.append(payload[index])
            index += 1
        while value_parts and value_parts[0] == labels[field]:
            value_parts.pop(0)
        if not value_parts or not all(value_parts):
            return None
        value = "|".join(value_parts)
        if not _is_unspecified_profile_value(value):
            profile_value = _profile_value(field, value)
            if profile_value:
                details[field] = profile_value
    return details


def _profile_relation(parts: list[str], *, allowed_names: set[str], existing: dict[str, str]) -> tuple[str, str] | None:
    if len(parts) == 3:
        name, value = parts[1:]
    elif len(parts) == 4 and parts[2] == "関係メモ":
        name, value = parts[1], parts[3]
    else:
        return None
    return (name, value) if name and value and name in allowed_names else None


def _should_discard_directional_relation(parts: list[str], subject_name: str) -> bool:
    """Keep only subject→other relations; reverse and third-party rows are irrelevant."""
    return len(parts) == 4 and parts[2] != "関係メモ" and parts[1] != subject_name


def _subject_directional_relation(
    parts: list[str], *, subject_name: str, allowed_names: set[str], existing: dict[str, str]
) -> tuple[str, str] | None:
    if len(parts) != 4 or parts[1] != subject_name:
        return None
    name, value = parts[2], parts[3]
    return (name, value) if name and value and name in allowed_names else None


def _json_profile_suggestion(
    raw: object,
    *,
    blank_fields: set[str],
    allowed_relation_names: set[str],
    allowed_relation_fields: dict[str, set[str]] | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, str]]] | None:
    try:
        parsed = json.loads(_text(raw))
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    details, relations = parsed.get("profile_details", {}), parsed.get("cast_relations", {})
    if not isinstance(details, dict) or not isinstance(relations, dict):
        return None
    accepted = {key: value for key, value in details.items() if key in blank_fields and value}
    name_relations: dict[str, dict[str, str]] = {}
    for name, value in relations.items():
        if name not in allowed_relation_names:
            continue
        source = value if isinstance(value, dict) else {"relationship": value}
        allowed = (allowed_relation_fields or {}).get(name, {"address", "relationship"})
        accepted_relation: dict[str, str] = {}
        for field in allowed:
            raw_value = source.get(field, source.get("note") if field == "relationship" else None)
            if isinstance(raw_value, str) and raw_value.strip():
                if accepted_value := deps.accepted_ai_relation_value(field, raw_value):
                    accepted_relation[field] = accepted_value
        if accepted_relation:
            name_relations[name] = accepted_relation
    return (accepted, name_relations) if accepted or name_relations else None


def _merge_unambiguous(target: dict[str, object], ambiguous: set[str], additions: dict[str, object]) -> None:
    for key, value in additions.items():
        if key in ambiguous:
            continue
        if key in target and target[key] != value:
            target.pop(key)
            ambiguous.add(key)
        elif key not in target:
            target[key] = value


def _accept_profile_relation_record(
    parts: list[str],
    *,
    relations: dict[str, dict[str, str]],
    ambiguous: set[str],
    subject_name: str,
    allowed_names: set[str],
    allowed_fields: dict[str, set[str]],
    priorities: dict[str, int],
) -> None:
    priority = 1
    if (
        len(parts) == 4
        and parts[1] in allowed_names
        and parts[2] not in allowed_names
        and parts[2] != subject_name
        and parts[2] not in {"呼び方", "関係性", "関係メモ"}
    ):
        name = parts[1]
        additions = {
            field: accepted_value
            for field, value in (("address", parts[2]), ("relationship", parts[3]))
            if value and field in allowed_fields.get(name, {"address", "relationship"})
            if (accepted_value := deps.accepted_ai_relation_value(field, value))
        }
        for field, value in additions.items():
            key = f"{name}:{field}"
            if key not in ambiguous and key not in priorities:
                relations.setdefault(name, {})[field] = value
                priorities[key] = priority
        return
    name = ""
    field = "relationship"
    value = ""
    if len(parts) == 4 and parts[1] in allowed_names and parts[2] in {"呼び方", "関係性"}:
        name, value = parts[1], parts[3]
        field = "address" if parts[2] == "呼び方" else "relationship"
        priority = 2
    elif not (subject_name and _should_discard_directional_relation(parts, subject_name)):
        legacy = (
            _subject_directional_relation(parts, subject_name=subject_name, allowed_names=allowed_names, existing={})
            if subject_name and len(parts) == 4 and parts[2] != "関係メモ"
            else _profile_relation(parts, allowed_names=allowed_names, existing={})
        )
        if legacy:
            name, value = legacy
    accepted_value = deps.accepted_ai_relation_value(field, value)
    if not name or not accepted_value or field not in allowed_fields.get(name, {"relationship"}):
        return
    value = accepted_value
    key = f"{name}:{field}"
    previous_priority = priorities.get(key)
    previous_value = relations.get(name, {}).get(field)
    if previous_priority is None or priority > previous_priority:
        ambiguous.discard(key)
        relations.setdefault(name, {})[field] = value
        priorities[key] = priority
    elif priority == previous_priority and previous_value != value:
        relations.get(name, {}).pop(field, None)
        ambiguous.add(key)


def parse_profile_suggestion(
    raw: object,
    *,
    labels: dict[str, str],
    blank_fields: set[str],
    allowed_relation_names: set[str],
    subject_name: str = "",
    allowed_relation_fields: dict[str, set[str]] | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, str]]] | None:
    if json_suggestion := _json_profile_suggestion(
        raw,
        blank_fields=blank_fields,
        allowed_relation_names=allowed_relation_names,
        allowed_relation_fields=allowed_relation_fields,
    ):
        return json_suggestion
    records = _profile_records(raw)
    if records is None:
        return None
    label_to_field = {label: field for field, label in labels.items()}
    details: dict[str, object] = {}
    relations: dict[str, dict[str, str]] = {}
    ambiguous_fields: set[str] = set()
    ambiguous_relations: set[str] = set()
    relation_priorities: dict[str, int] = {}
    for parts in records:
        kind = parts[0]
        if kind == "FIELD":
            # The character name is controlled by the editor, not this
            # completion.  Small models sometimes emit it as a harmless
            # heading before otherwise valid profile fields.
            if len(parts) == 3 and parts[1] == "表示名":
                continue
            if len(parts) == 4 and parts[1] in blank_fields and parts[2] == labels.get(parts[1]):
                field = parts[1]
                profile_value = _profile_value(field, parts[3]) if parts[3] else None
                additions = {field: profile_value} if profile_value and not _is_unspecified_profile_value(parts[3]) else {}
            elif len(parts) == 3:
                field = _standard_profile_field(
                    parts[1], label_to_field=label_to_field, blank_fields=blank_fields, details=details
                )
                profile_value = _profile_value(field, parts[2]) if field and parts[2] else None
                additions = (
                    {}
                    if field and (_is_unspecified_profile_value(parts[2]) or not profile_value)
                    else {field: profile_value}
                    if field and parts[2]
                    else None
                )
            else:
                additions = _packed_profile_fields(parts, labels=labels, blank_fields=blank_fields)
            if additions:
                _merge_unambiguous(
                    details,
                    ambiguous_fields,
                    {field: value for field, value in additions.items() if field in blank_fields},
                )
        elif kind == "RELATION":
            _accept_profile_relation_record(
                parts,
                relations=relations,
                ambiguous=ambiguous_relations,
                subject_name=subject_name,
                allowed_names=allowed_relation_names,
                allowed_fields=allowed_relation_fields or {},
                priorities=relation_priorities,
            )
    return (details, relations) if details or relations else None


deps.register(__name__, ["parse_profile_suggestion"])

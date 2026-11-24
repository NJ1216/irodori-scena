from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from server.registry import deps
from server.modules.json_offsets import decode_at

MAX_RECORDS = 2048
MAX_RECORD_BYTES = 1_048_576
MAX_NESTING = 32


def _array_after_key(content: str, cursor: int, value: Any) -> int | None:
    if value != "records":
        return None
    while cursor < len(content) and content[cursor].isspace():
        cursor += 1
    if cursor >= len(content) or content[cursor] != ":":
        return None
    cursor += 1
    while cursor < len(content) and content[cursor].isspace():
        cursor += 1
    return cursor + 1 if cursor < len(content) and content[cursor] == "[" else None


@dataclass(frozen=True)
class LlmTextContract:
    name: str
    version: int
    wrappers: tuple[str, ...] = ("markdown_fence", "harmony")


@dataclass(frozen=True)
class LlmRecordContract:
    name: str
    version: int
    schema: dict[str, Any]
    owner_key: str
    aliases: frozenset[str] = frozenset()
    legacy_suffix: str = ""
    legacy_parser: Callable[[str], Any] | None = None
    merge_by_owner: bool = True
    loop_projection: Callable[[list[dict[str, Any]]], str] | None = None
    response_schema_override: dict[str, Any] | None = None
    record_extractor: Callable[[str], tuple[list[dict[str, Any]], bool]] | None = None

    @property
    def response_schema(self) -> dict[str, Any]:
        if self.response_schema_override is not None:
            return self.response_schema_override
        return {
            "type": "object",
            "properties": {"records": {"type": "array", "items": self.schema}},
            "required": ["records"],
            "additionalProperties": False,
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.response_schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def extract_contract_records(content: str, contract: LlmRecordContract) -> tuple[list[dict[str, Any]], bool]:
    if contract.record_extractor is not None:
        return contract.record_extractor(content)
    return extract_complete_records(content)


@dataclass(frozen=True)
class LlmTransportResult:
    content: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None
    refusal: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    partial: bool = False
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class LlmContractResult:
    records: tuple[dict[str, Any], ...]
    mode: Literal["schema", "legacy"]
    raw_response: str
    manifest: tuple[dict[str, Any], ...]
    transport: LlmTransportResult


def _records_array_start(content: str) -> int | None:
    """Find a root object's records array without accepting a nested lookalike."""
    decoder = json.JSONDecoder()
    for root in (index for index, character in enumerate(content) if character == "{"):
        depth, index, in_string, escaped = 1, root + 1, False, False
        while index < len(content) and depth:
            character = content[index]
            if in_string:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    in_string = False
                index += 1
                continue
            if character == '"' and depth == 1:
                try:
                    value, end = decode_at(decoder, content, index)
                except json.JSONDecodeError:
                    break
                if (array_start := _array_after_key(content, end, value)) is not None:
                    return array_start
                index = end
                continue
            if character == '"':
                in_string = True
            elif character in "{[":
                depth += 1
            elif character in "}]":
                depth -= 1
            index += 1
    return None


def _value_depth(value: Any, depth: int = 0) -> int:
    if depth > MAX_NESTING:
        raise ValueError("LLM record nesting limit exceeded")
    children = value.values() if isinstance(value, dict) else value if isinstance(value, list) else ()
    for child in children:
        _value_depth(child, depth + 1)
    return depth


def extract_complete_records(content: str) -> tuple[list[dict[str, Any]], bool]:
    """Extract every closed root records item, retaining prefix records on truncation."""
    start = _records_array_start(content)
    if start is None:
        return [], True
    decoder = json.JSONDecoder()
    records: list[dict[str, Any]] = []
    index = start
    while index < len(content):
        while index < len(content) and (content[index].isspace() or content[index] == ","):
            index += 1
        if index >= len(content) or content[index] == "]":
            return records, index >= len(content)
        if content[index] != "{":
            return records, True
        try:
            record, end = decode_at(decoder, content, index)
        except json.JSONDecodeError:
            return records, True
        raw = content[index:end]
        if len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
            raise ValueError("LLM record size limit exceeded")
        if isinstance(record, dict):
            _value_depth(record)
            records.append(record)
        if len(records) > MAX_RECORDS:
            raise ValueError("LLM record count limit exceeded")
        index = end
    return records, True


def _schema_value_is_valid(value: Any, spec: dict[str, Any], depth: int = 0) -> bool:
    if depth > MAX_NESTING:
        return False
    declared = spec.get("type")
    allowed = [declared] if isinstance(declared, str) else declared if isinstance(declared, list) else []
    if value is None:
        valid = "null" in allowed
    elif type(value) is bool:
        valid = "boolean" in allowed
    elif type(value) is int:
        valid = "integer" in allowed or "number" in allowed
    elif type(value) is float:
        valid = "number" in allowed
    elif isinstance(value, str):
        valid = "string" in allowed
    elif isinstance(value, list):
        valid = "array" in allowed
        item_spec = spec.get("items")
        if valid and isinstance(item_spec, dict):
            valid = all(_schema_value_is_valid(item, item_spec, depth + 1) for item in value)
    elif isinstance(value, dict):
        valid = "object" in allowed
        properties = spec.get("properties", {})
        if valid and spec.get("additionalProperties") is False:
            valid = all(key in properties for key in value)
        required = spec.get("required", [])
        if valid:
            valid = all(key in value for key in required)
        if valid:
            valid = all(
                not isinstance(properties.get(key), dict)
                or _schema_value_is_valid(item, properties[key], depth + 1)
                for key, item in value.items() if key in properties
            )
    else:
        valid = False
    return valid and ("enum" not in spec or value in spec["enum"])


def validate_record_fields(record: dict[str, Any], contract: LlmRecordContract) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    properties = contract.schema.get("properties", {})
    owner = record.get(contract.owner_key)
    manifest: list[dict[str, Any]] = []
    if not isinstance(owner, str) or (contract.aliases and owner not in contract.aliases):
        return None, [{"status": "rejected", "reason": "unknown_owner", "field": contract.owner_key}]
    accepted: dict[str, Any] = {contract.owner_key: owner}
    for key, value in record.items():
        if key == contract.owner_key:
            continue
        spec = properties.get(key)
        if not isinstance(spec, dict):
            manifest.append({"status": "rejected", "reason": "unknown_field", "owner": owner, "field": key})
            continue
        if _schema_value_is_valid(value, spec):
            accepted[key] = value
            manifest.append({"status": "accepted", "owner": owner, "field": key})
        else:
            manifest.append({"status": "rejected", "reason": "invalid_field", "owner": owner, "field": key})
    if contract.name == "draft-dialogue":
        if not accepted.get("speaker") or not accepted.get("text"):
            return None, manifest
        text = deps.strip_draft_emojis(accepted["text"])
        if text != accepted["text"]:
            manifest.append({"status": "normalized", "reason": "prohibited_emoji", "owner": owner, "field": "text"})
        accepted["text"] = text
        if not text.strip():
            return None, manifest
    return accepted, manifest


def merge_record_fields(records: list[dict[str, Any]], contract: LlmRecordContract) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not contract.merge_by_owner:
        cleaned, manifest = [], []
        for record in records:
            accepted, decisions = validate_record_fields(record, contract)
            manifest.extend(decisions)
            if accepted is not None:
                cleaned.append(accepted)
        return cleaned, manifest
    merged: dict[str, dict[str, Any]] = {}
    conflicted: set[tuple[str, str]] = set()
    manifest: list[dict[str, Any]] = []
    order: list[str] = []
    for record in records:
        clean, decisions = validate_record_fields(record, contract)
        manifest.extend(decisions)
        if clean is None:
            continue
        owner = clean[contract.owner_key]
        if owner not in merged:
            merged[owner] = {contract.owner_key: owner}
            order.append(owner)
        for key, value in clean.items():
            if key == contract.owner_key or (owner, key) in conflicted:
                continue
            if key not in merged[owner] or merged[owner][key] == value:
                merged[owner][key] = value
            else:
                merged[owner].pop(key, None)
                conflicted.add((owner, key))
                manifest.append({"status": "rejected", "reason": "conflicting_field", "owner": owner, "field": key})
    return [merged[owner] for owner in order], manifest


TEXT_CONTRACTS = {
    name: LlmTextContract(name, 1) for name in (
        "theme-suggestion", "script-context-summary", "rewrite-policy", "character-profile",
        "cast-relations", "pronunciation", "image-prompt", "draft-planning", "draft-dialogue",
        "draft-direction", "draft-repair", "draft-notation", "script-assistant", "instruction",
        "script-assistant-dialogue", "script-assistant-rewrite-plan", "draft-chapter-detail",
    )
}


deps.register(__name__, [
    "LlmContractResult", "LlmRecordContract", "LlmTextContract", "LlmTransportResult",
    "TEXT_CONTRACTS", "extract_complete_records", "extract_contract_records",
    "merge_record_fields", "validate_record_fields",
])

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from server.registry import deps


def build_address_registries(targets: list[dict[str, Any]], subject_core: dict[str, Any]) -> dict[str, dict[str, Any]]:
    honorifics = deps.allowed_honorifics(subject_core)
    registries = {}
    for target_index, target in enumerate(targets, 1):
        original = deps.address_candidates(target["source_cast"], subject_core)
        scoped = [replace(candidate, id=f"R{target_index}C{index}") for index, candidate in enumerate(original, 1)]
        registries[target["id"]] = {
            "candidates": scoped, "legacyCandidateIds": {
                original_candidate.id: scoped_candidate.id
                for original_candidate, scoped_candidate in zip(original, scoped, strict=True)
            }, "honorifics": honorifics,
        }
    return registries


def prompt_address_options(target: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any]:
    return {
        "address_candidates": [asdict(candidate) for candidate in registry["candidates"]],
        "honorifics": [{"id": key, "value": value or "なし"} for key, value in registry["honorifics"].items()],
        **{key: value for key, value in target.items()
           if key not in {"source_cast", "normalized_existing_address"}},
    }


def relation_record_contract(targets: list[dict[str, Any]], registries: dict[str, dict[str, Any]]) -> Any:
    target_ids = [item["id"] for item in targets]
    candidate_ids = sorted({candidate.id for target in targets for candidate in registries[target["id"]]["candidates"]})
    honorific_ids = sorted({key for target in targets for key in registries[target["id"]]["honorifics"]})
    nullable_string = {"type": ["string", "null"]}
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "target": {"type": "string", "enum": target_ids},
            "relationship": nullable_string,
            "candidate": {"type": ["string", "null"], "enum": [*candidate_ids, None]},
            "custom": nullable_string,
            "honorific": {"type": ["string", "null"], "enum": [*honorific_ids, None]},
            "basis": {"type": ["string", "null"], "enum": [
                "name", "alias", "pronoun", "formal_title", "relational_nickname", None,
            ]},
        },
        "required": ["target", "relationship", "candidate", "custom", "honorific", "basis"],
    }
    return deps.LlmRecordContract(
        "cast-relations", 1, schema, "target", frozenset(target_ids),
        legacy_suffix="各行をRELATION形式で返す。JSONや説明は出力しない。",
    )


def resolve_relation_records(records: list[dict[str, Any]], targets: list[dict[str, Any]],
                             registries: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    accepted: dict[str, dict[str, str]] = {}
    manifest: list[dict[str, Any]] = []
    allowed_by_target = {item["id"]: set(item["missing_relation_fields"]) for item in targets}
    for record in records:
        target = record.get("target")
        if target not in allowed_by_target:
            continue
        if "relationship" in allowed_by_target[target] and isinstance(record.get("relationship"), str):
            relationship = record["relationship"].strip()
            if relationship:
                accepted.setdefault(target, {})["relationship"] = relationship
                manifest.append({"status": "accepted", "targetId": target, "field": "relationship"})
        if "address" not in allowed_by_target[target]:
            continue
        registry = registries[target]
        candidate, custom = record.get("candidate"), record.get("custom")
        honorific, basis = record.get("honorific"), record.get("basis")
        if isinstance(candidate, str) and isinstance(honorific, str) and isinstance(basis, str) and custom is None:
            value, reason = deps.resolve_candidate_address(
                candidate_id=candidate, honorific_id=honorific, basis=basis,
                candidates=registry["candidates"], honorifics=registry["honorifics"],
            )
        elif isinstance(custom, str) and isinstance(honorific, str) and isinstance(basis, str) and candidate is None:
            value, reason = deps.resolve_custom_address(custom, honorific, basis, registry["honorifics"])
        else:
            value, reason = None, "ambiguous_address"
        manifest.append({"status": "accepted" if value else "rejected", "targetId": target,
                         "field": "address", "reason": reason})
        if value:
            accepted.setdefault(target, {})["address"] = value
    return accepted, manifest


def _target_key(raw: str, targets: list[dict[str, Any]]) -> str | None:
    direct = next((item["id"] for item in targets if item["id"] == raw), None)
    if direct:
        return direct
    matches = [item["id"] for item in targets if item["name"] == raw]
    return matches[0] if len(matches) == 1 else None


def _resolve_address(parts: list[str], registry: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    manifest: dict[str, Any] = {"status": "rejected", "reason": "invalid_address_record"}
    if len(parts) == 6 and parts[2] == "呼び方候補":
        candidate_id, honorific_id, basis = parts[3:6]
        candidate_id = registry.get("legacyCandidateIds", {}).get(candidate_id, candidate_id)
        value, reason = deps.resolve_candidate_address(
            candidate_id=candidate_id, honorific_id=honorific_id, basis=basis,
            candidates=registry["candidates"], honorifics=registry["honorifics"],
        )
        manifest.update({"candidateId": candidate_id, "honorificId": honorific_id, "basis": basis})
    elif len(parts) == 6 and parts[2] == "設定呼称":
        custom, honorific_id, basis = parts[3:6]
        value, reason = deps.resolve_custom_address(custom, honorific_id, basis, registry["honorifics"])
        manifest.update({"custom": custom, "honorificId": honorific_id, "basis": basis})
    elif len(parts) == 4 and parts[2] == "呼び方":
        # Older models may echo a completed value. It is accepted only when it
        # resolves to one of the advertised candidate/honorific combinations.
        completed = parts[3]
        matches = [
            (candidate, honorific_id)
            for candidate in registry["candidates"]
            for honorific_id, honorific in registry["honorifics"].items()
            if candidate.value + honorific == completed
        ]
        if len(matches) != 1:
            return None, {**manifest, "reason": "legacy_value_not_in_registry"}
        candidate, honorific_id = matches[0]
        value, reason = deps.resolve_candidate_address(
            candidate_id=candidate.id, honorific_id=honorific_id, basis=candidate.kind,
            candidates=registry["candidates"], honorifics=registry["honorifics"],
        )
        manifest.update({"candidateId": candidate.id, "honorificId": honorific_id,
                         "basis": candidate.kind, "legacy": True})
    else:
        return None, manifest
    manifest.update({"status": "accepted" if value else "rejected", "reason": reason})
    return value, manifest


def _normalized_address(parts: list[str], registry: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """Resolve legacy ID/value mixtures only when the advertised registry is unambiguous."""
    value, manifest = _resolve_address(parts, registry)
    if value or len(parts) < 4:
        return value, manifest
    payload = [item for item in parts[3:] if item]
    candidates = registry["candidates"]
    honorifics = registry["honorifics"]
    matches: list[tuple[Any, str]] = []
    for candidate in candidates:
        for honorific_id, honorific in honorifics.items():
            completed = candidate.value + honorific
            advertised = {candidate.id, candidate.value, completed}
            honorific_values = {honorific_id, honorific or "なし"}
            if any(token in advertised for token in payload) and all(
                token in advertised or token in honorific_values or token == candidate.kind for token in payload
            ):
                matches.append((candidate, honorific_id))
    unique = {(candidate.id, honorific_id): (candidate, honorific_id) for candidate, honorific_id in matches}
    if len(unique) != 1:
        return None, {**manifest, "reason": "legacy_value_not_in_registry"}
    candidate, honorific_id = next(iter(unique.values()))
    resolved, reason = deps.resolve_candidate_address(
        candidate_id=candidate.id, honorific_id=honorific_id, basis=candidate.kind,
        candidates=candidates, honorifics=honorifics,
    )
    return resolved, {"status": "accepted" if resolved else "rejected", "reason": reason,
                      "candidateId": candidate.id, "honorificId": honorific_id,
                      "basis": candidate.kind, "legacy": True}


def parse_relation_response(content: str, targets: list[dict[str, Any]], registries: dict[str, dict[str, Any]]) -> tuple[dict[str, dict[str, str]], list[dict[str, Any]]]:
    relations: dict[str, dict[str, str]] = {}
    manifests: list[dict[str, Any]] = []
    for line in content.splitlines():
        parts = [part.strip() for part in line.strip().split("|")]
        while len(parts) > 1 and parts[0] == parts[1] == "RELATION":
            parts.pop(0)
        if len(parts) < 4 or parts[0] != "RELATION":
            continue
        target_id = _target_key(parts[1], targets)
        if not target_id:
            continue
        allowed = next(item["missing_relation_fields"] for item in targets if item["id"] == target_id)
        if parts[2] == "関係性" and "relationship" in allowed and parts[3]:
            current = relations.setdefault(target_id, {})
            relationship = parts[3].strip()
            if "relationship" not in current:
                current["relationship"] = relationship
            elif current["relationship"] != relationship:
                current.pop("relationship", None)
            continue
        if "address" not in allowed:
            continue
        value, manifest = _normalized_address(parts, registries[target_id])
        manifest["targetId"] = target_id
        manifests.append(manifest)
        if value:
            current = relations.setdefault(target_id, {})
            if "address" not in current:
                current["address"] = value
            elif current["address"] != value:
                current.pop("address", None)
                manifest.update({"status": "rejected", "reason": "conflicting_address"})
    return relations, manifests


deps.register(__name__, ["build_address_registries", "parse_relation_response", "prompt_address_options",
                         "relation_record_contract", "resolve_relation_records"])

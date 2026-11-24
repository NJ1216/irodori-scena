from __future__ import annotations

from server.app_deps import Any, parse_context_selection, parse_plan_protocol
from server.registry import deps
from server.modules.partial_json import extract_partial_records, scan_json_object
from copy import deepcopy


def _fallback_partial_plan_records(content):
    root = scan_json_object(content)
    rows = []
    fields = root.fields()
    title = fields.get("title") or fields.get("script_title")
    story = fields.get("story_bible") or fields.get("story")
    if title and title.closed and isinstance(title.value, str):
        rows.append({"kind": "title", "text": title.value})
    if story and story.closed and isinstance(story.value, str):
        rows.append({"kind": "story", "text": story.value})
    chapters = fields.get("chapters")
    if chapters and chapters.kind == "array":
        aliases = {
            "chapter_index": "index",
            "chapter_title": "title",
            "purpose": "objective",
            "developments": "beats",
            "start_state": "opening",
            "end_state": "closing",
            "continuity_requirements": "continuity",
            "novelty_requirement": "novelty",
        }
        for item in chapters.items:
            if item.kind != "object":
                continue
            chapter = item.materialize()
            row = {"kind": "chapter"}
            for source, target in aliases.items():
                if source in chapter:
                    row[target] = chapter[source]
            for key in (
                "index",
                "title",
                "objective",
                "beats",
                "continuity",
                "opening",
                "closing",
                "novelty",
                "scenes",
            ):
                if key in chapter:
                    row[key] = chapter[key]
            has_content = any(
                row.get(key)
                for key in (
                    "title",
                    "objective",
                    "beats",
                    "continuity",
                    "opening",
                    "closing",
                    "novelty",
                    "scenes",
                )
            )
            if isinstance(row.get("index"), int) and has_content:
                rows.append(row)
    partial = not root.closed or not chapters or not chapters.closed
    return rows, partial


def _partial_plan_records(content):
    rows, partial = extract_partial_records(content)
    if not rows:
        rows, partial = _fallback_partial_plan_records(content)
    for row in rows:
        scenes = row.get("scenes")
        if isinstance(scenes, list):
            row["scenes"] = [{key: deps.strip_draft_emojis(value) for key, value in scene.items() if key in {"purpose", "start", "end"} and isinstance(value, str)} for scene in scenes if isinstance(scene, dict) and isinstance(scene.get("purpose"), str)]
            row["scenes"] = [scene for scene in row["scenes"] if scene.get("purpose", "").strip()]
        for key in ("beats", "continuity"):
            if isinstance(row.get(key), list):
                row[key] = [deps.strip_draft_emojis(value) for value in row[key] if isinstance(value, str)]
    return rows, partial


def _legacy_plan_records(content: str) -> list[dict[str, Any]]:
    plan = parse_plan_protocol(content)
    records: list[dict[str, Any]] = []
    if plan.get("title"):
        records.append({"kind": "title", "text": plan["title"]})
    if plan.get("story_bible"):
        records.append({"kind": "story", "text": plan["story_bible"]})
    for alias, value in plan.get("cast_contexts", {}).items():
        records.append({"kind": "cast", "alias": alias, "role": value.get("role"), "text": value.get("description")})
    for index, chapter in enumerate(plan.get("chapters", []), 1):
        records.append(
            {
                "kind": "chapter",
                "index": index,
                "title": chapter.get("title"),
                "objective": chapter.get("objective"),
                "beats": chapter.get("beats", []),
                "continuity": chapter.get("continuity_requirements", []),
                "opening": chapter.get("opening_state"),
                "closing": chapter.get("closing_state"),
                "novelty": chapter.get("novelty_requirement"),
                "scenes": None,
            }
        )
    return records


def draft_plan_contract(cast_aliases: set[str]):
    def nullable(kind: str) -> dict[str, list[str]]:
        return {"type": [kind, "null"]}

    scene = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "purpose": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
        },
        "required": ["purpose", "start", "end"],
    }
    properties = {
        "kind": {"type": "string", "enum": ["title", "story", "cast", "chapter", "ending"]},
        "index": nullable("integer"),
        "alias": {"type": ["string", "null"], "enum": [*sorted(cast_aliases), None]},
        "title": nullable("string"),
        "text": nullable("string"),
        "role": nullable("string"),
        "objective": nullable("string"),
        "beats": {"type": ["array", "null"], "items": {"type": "string"}},
        "continuity": {"type": ["array", "null"], "items": {"type": "string"}},
        "opening": nullable("string"),
        "closing": nullable("string"),
        "novelty": nullable("string"),
        "scenes": {"type": ["array", "null"], "items": scene},
    }
    schema = {"type": "object", "additionalProperties": False, "properties": properties, "required": list(properties)}
    variants = []
    for kind, fields in {
        "title": ["text"],
        "story": ["text"],
        "ending": ["text"],
        "cast": ["alias", "role", "text"],
        "chapter": ["index", "title", "objective", "scenes", "opening", "closing", "novelty"],
    }.items():
        selected = {"kind": {"type": "string", "enum": [kind]}, **{key: deepcopy(properties[key]) for key in fields}}
        variants.append({"type": "object", "additionalProperties": False, "properties": selected, "required": list(selected)})
    response_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"records": {"type": "array", "items": {"anyOf": variants}}},
        "required": ["records"],
    }
    # Receive old nullable records and individually usable partial scenes too.
    schema["properties"]["scenes"]["items"] = {**scene, "required": ["purpose"]}
    return deps.LlmRecordContract(
        "draft-planning",
        2,
        schema,
        "kind",
        frozenset({"title", "story", "cast", "chapter", "ending"}),
        legacy_suffix="TITLE/STORY/CAST_CONTEXT/CHAPTER各行の既定形式だけを返す。",
        legacy_parser=_legacy_plan_records,
        merge_by_owner=False,
        response_schema_override=response_schema,
        record_extractor=_partial_plan_records,
    )


def plan_from_records(records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    plan: dict[str, Any] = {"title": "", "story_bible": "", "cast_contexts": {}, "chapters": []}
    indexed: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        kind = record.get("kind")
        if kind == "ending" and isinstance(record.get("text"), str):
            plan.setdefault("ending_quotes", []).append(record["text"])
        if kind == "title" and not plan["title"] and record.get("text"):
            plan["title"] = record["text"]
        if kind == "story" and record.get("text"):
            plan["story_bible"] = " ".join(filter(None, [plan["story_bible"], record["text"]]))
        if kind == "cast" and record.get("alias") and record.get("text"):
            plan["cast_contexts"].setdefault(
                record["alias"],
                {
                    "role": record.get("role") or "登場人物",
                    "description": record["text"],
                },
            )
        # Some constrained local models collapse several requested records into
        # one object and leave ``kind`` set to the first record.  An integer
        # index plus chapter-only content makes ownership unambiguous, so retain
        # those useful sibling fields instead of rejecting the whole outline.
        has_chapter_content = any(
            record.get(field)
            for field in (
                "objective",
                "beats",
                "continuity",
                "opening",
                "closing",
                "novelty",
                "scenes",
            )
        )
        if isinstance(record.get("index"), int) and (kind == "chapter" or has_chapter_content):
            scenes = record.get("scenes") if isinstance(record.get("scenes"), list) else []
            semantic_beats = [f"開始状態: {scene.get('start', '')} / 目的: {scene.get('purpose', '')} / 終了状態: {scene.get('end', '')}" for scene in scenes if isinstance(scene, dict) and str(scene.get("purpose", "")).strip()]
            indexed.append(
                (
                    record["index"],
                    {
                        "title": record.get("title") or "",
                        "objective": record.get("objective") or "",
                        "beats": semantic_beats or record.get("beats") or [],
                        "semantic_scenes": scenes,
                        "continuity_requirements": record.get("continuity") or [],
                        "opening_state": record.get("opening") or "",
                        "closing_state": record.get("closing") or "",
                        "novelty_requirement": record.get("novelty") or "",
                    },
                )
            )
    plan["chapters"] = [chapter for _, chapter in sorted(indexed, key=lambda item: item[0])]
    return plan


def chapter_detail_contract():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string", "enum": ["development"]},
            "text": {"type": "string"},
        },
        "required": ["kind", "text"],
    }

    def legacy(content: str):
        return [{"kind": "development", "text": raw.strip().split("|", 1)[1]} for raw in content.replace("\r\n", "\n").split("\n") if raw.strip().startswith("DEVELOPMENT|")]

    return deps.LlmRecordContract(
        "draft-chapter-detail",
        1,
        schema,
        "kind",
        frozenset({"development"}),
        legacy_suffix="一行一件のDEVELOPMENT|具体的展開だけを返す。",
        legacy_parser=legacy,
        merge_by_owner=False,
    )


def context_selection_contract(cast_aliases: set[str], fields: set[str]):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cast": {"type": "string", "enum": sorted(cast_aliases)},
            "field": {"type": "string", "enum": sorted(fields)},
        },
        "required": ["cast", "field"],
    }

    def legacy(content: str):
        selected = parse_context_selection(content, allowed_cast_ids=cast_aliases, allowed_fields=fields)
        return [{"cast": alias, "field": field} for alias, values in selected.items() for field in sorted(values)]

    return deps.LlmRecordContract(
        "draft-context-selection",
        1,
        schema,
        "cast",
        frozenset(cast_aliases),
        legacy_suffix="必要な項目だけをA|field形式で返し、不要ならNONEとする。",
        legacy_parser=legacy,
        merge_by_owner=False,
    )


deps.register(__name__, ["chapter_detail_contract", "context_selection_contract", "draft_plan_contract", "plan_from_records"])

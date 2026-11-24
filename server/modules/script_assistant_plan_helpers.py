"""Pure row and context helpers for script-assistant planning."""

from __future__ import annotations

from typing import Any

from server.modules.script_assistant_cast_composition import mask_cast_composition_rows
from server.modules.script_assistant_fitting import fits
from server.registry import deps


def _summary_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        **({"distant_context": context["distant_context"]} if context["distant_context"] else {}),
        **({"middle_context": context["middle_context"]} if context["middle_context"] else {}),
    }


def _compact_plan_rows(rows: list[dict[str, Any]], *, directions: bool = True) -> list[dict[str, Any]]:
    return [{
        "speaker": row.get("speaker", ""), "text": row.get("text", ""),
        **({"direction": row["stage_direction"]} if directions and row.get("stage_direction") else {}),
        **({"cue": row["cue_id"]} if row.get("cue_id") else {}),
    } for row in rows]


def _fit_rewrite_plan_user(system: str, value: dict[str, Any]) -> dict[str, Any]:
    """Drop only optional plan context, preserving the author's request and target text."""
    minimum_output = 256
    if fits(system, value, minimum_output):
        return value
    value["recent_confirmed_context"] = []
    value.pop("distant_context", None)
    value.pop("middle_context", None)
    if fits(system, value, minimum_output):
        return value
    value["selected_cast_index"] = [{**item, "role": str(item.get("role", ""))[:160]}
                                     for item in value["selected_cast_index"]]
    if fits(system, value, minimum_output):
        return value
    for key in ("original_target_rows", "immutable_rows_inside_selection", "following_three_rows"):
        value[key] = [{name: field for name, field in row.items() if name != "direction"} for row in value[key]]
    return value


def _normalize_proposal_cues(rows: list[dict[str, Any]], *, allowed: bool) -> None:
    for row in rows:
        row.pop("proposalCueId", None)
        row.pop("startOffsetSeconds", None)
    if not allowed:
        return
    index = 0
    while index < len(rows):
        marker = rows[index].get("cueMarker")
        end = index + 1
        while marker and end < len(rows) and rows[end].get("cueMarker") == marker:
            end += 1
        members = rows[index:end]
        if marker and 2 <= len(members) <= 8 and len({row["characterId"] for row in members}) == len(members):
            cue_id = deps.new_id("assistant_cue")
            trailing_gap = members[-1].get("gapSeconds")
            for member in members:
                member["proposalCueId"] = cue_id
                member["startOffsetSeconds"] = 0.0
                member.pop("gapSeconds", None)
            if trailing_gap is not None:
                members[0]["gapSeconds"] = trailing_gap
        index = end if marker else index + 1
    for row in rows:
        row.pop("cueMarker", None)


def _original_target_context(
    request: Any, selected: list[dict[str, Any]], originals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if request.operation == "paraphrase":
        positions = {str(row.get("id") or row.get("line_id", "")): index + 1 for index, row in enumerate(originals or selected)}
        return {"original_target_rows": [
            mask_cast_composition_rows([row], start_index=positions.get(str(row.get("id") or row.get("line_id", "")), 1))[0]
            for row in selected
        ]}
    if request.operation == "cast-compose":
        return {"original_target_rows": mask_cast_composition_rows(selected)}
    return {}

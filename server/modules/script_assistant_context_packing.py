from __future__ import annotations

from typing import Any

from server.modules.script_assistant_summary import summarize_unit
from server.registry import deps


def dialogue_row(item: dict[str, Any]) -> dict[str, str]:
    """The only row projection allowed into graduated context prompts."""
    return {"speaker": str(item.get("speaker", "")), "text": str(item.get("line", {}).get("text", ""))}


def target_row(item: dict[str, Any]) -> dict[str, str]:
    line = item.get("line", {})
    return {
        "line_id": str(line.get("id", "")), "character_id": str(line.get("characterId", "")),
        "speaker": str(item.get("speaker", "")), "text": str(line.get("text", "")),
    }


def pack_script_assistant_context(
    request: Any, job_id: str, context: dict[str, Any], debug: Any, *, call: Any,
) -> dict[str, Any]:
    # A model/project switch ends the previous summary-cache scope.
    current_scope = (context["projectId"], str(getattr(request, "model", "")))
    with deps.SCRIPT_ASSISTANT_SUMMARY_CACHE_LOCK:
        for key in list(deps.SCRIPT_ASSISTANT_SUMMARY_CACHE):
            if (key[0], key[3]) != current_scope:
                deps.SCRIPT_ASSISTANT_SUMMARY_CACHE.pop(key, None)
    distant = []
    for unit in context["distantUnits"]:
        summary = summarize_unit(
            request, job_id, context["projectId"], unit["id"], unit["rows"], "distant-v1", debug, call=call,
        )
        if summary:
            distant.append({"chapter": unit["title"] or unit["id"], "summary": summary})
    middle = ""
    if context["middleRows"]:
        middle = summarize_unit(
            request, job_id, context["projectId"], context["targetChapter"], context["middleRows"],
            "middle-v1", debug, call=call,
        )
    return {
        "distant_context": distant, "middle_context": middle,
        "recent": [dialogue_row(item) for item in context["recentRows"]],
        "selected": [target_row(item) for item in context["selectedRows"]],
        "anchors": [dialogue_row(item) for item in context["anchorRows"]],
        "following": [dialogue_row(item) for item in context["followingRows"]],
        "_reference_ids": {
            str(item.get("line", {}).get("characterId", ""))
            for key in ("recentRows", "selectedRows", "anchorRows", "followingRows")
            for item in context[key] if item.get("line", {}).get("characterId")
        },
    }


def explicit_reference_ids(project: dict[str, Any], instruction: str) -> set[str]:
    """Resolve only unique exact cast-name mentions; ambiguous names stay unresolved."""
    by_name: dict[str, list[str]] = {}
    for character in project.get("characters", []):
        name = str(character.get("name", "")).strip()
        character_id = str(character.get("id", "")).strip()
        if name and character_id:
            by_name.setdefault(name, []).append(character_id)
    return {
        ids[0] for name, ids in by_name.items()
        if len(ids) == 1 and name in instruction
    }


deps.register(__name__, ["dialogue_row", "pack_script_assistant_context"])

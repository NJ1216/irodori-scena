from __future__ import annotations

from typing import Any

from server.registry import deps


def accepted_draft_context(drafted: list[dict[str, Any]]) -> dict[str, Any]:
    """Every call continues from global accepted dialogue, including chapter transitions."""
    return {"lines": [line for item in drafted for line in item["dialogue"].get("lines", [])]}


def draft_completion_ledger(chapters, developments, pending, completed_source_ids):
    source_text = {item.split("|", 1)[0]: item.split("|", 1)[1]
                   for items in developments for item in items if "|" in item}
    completed_chapters = [index for index, items in enumerate(pending) if not items and developments[index]]
    return {
        "completed_sources": [{"source_id": source, "development": source_text.get(source, "")}
                              for source in completed_source_ids],
        "completed_chapters": [index + 1 for index in completed_chapters],
        "confirmed_closing_states": [
            {"chapter": index + 1, "state": str(chapters[index].get("closing_state", "")).strip()}
            for index in completed_chapters if str(chapters[index].get("closing_state", "")).strip()
        ],
    }


deps.register(__name__, ["accepted_draft_context", "draft_completion_ledger"])

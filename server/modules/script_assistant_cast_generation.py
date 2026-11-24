from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from server.draft_protocol import parse_dialogue_protocol
from server.modules.script_assistant_cast_composition import (
    cast_composition_changes,
    mask_cast_composition_rows,
)
from server.modules.script_assistant_prompt import _author_instruction, _system_prompt
from server.modules.script_assistant_fitting import largest_fitting_prefix, output_reservation
from server.registry import deps


def _processed_tail(
    previous: list[dict[str, Any]], batch: list[dict[str, Any]], changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changed = {str(row.get("originalLineId", "")): row for row in changes}
    processed = []
    for source in batch:
        replacement = changed.get(str(source.get("id", "")))
        processed.append({
            "line_id": source.get("id"), "character_id": source.get("characterId"),
            "text": replacement.get("text") if replacement else source.get("text", ""),
            "stage_direction": source.get("stageDirection", ""),
        })
    return (previous + processed)[-5:]


def generate_cast_composition_rows(
    request: Any, job_id: str, group: dict[str, Any], context: dict[str, Any], cast: list[dict[str, Any]],
    alias_to_id: dict[str, str], summary: str, debug: Path, group_index: int, group_total: int,
    *, call: Callable[..., str], update: Callable[..., None], direct_rows: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int, str]:
    originals = group["originalLines"]
    rows: list[dict[str, Any]] = []
    reviewed_count = 0
    processed_tail: list[dict[str, Any]] = []
    id_to_alias = {character_id: alias for alias, character_id in alias_to_id.items()}
    targets = [
        (character_id, [row for row in originals if str(row.get("characterId", "")) == character_id])
        for character_id in request.character_ids
    ]
    targets = [(character_id, target_rows) for character_id, target_rows in targets if target_rows]
    processed_count = 0
    call_index = 0
    for character_id, target_rows in targets:
      pending = list(target_rows)
      target_cast = [item for item in cast if str(item.get("alias", "")) == id_to_alias.get(character_id)]
      while pending:
        system = _system_prompt(request, group)

        def build_user(candidate: list[dict[str, Any]]) -> dict[str, Any]:
            last = originals.index(candidate[-1]) + 1
            following = originals[last:last + 3]
            if len(following) < 3:
                following += context["following"][:3 - len(following)]
            return {
                "author_instruction": _author_instruction(request), "selected_casts": target_cast,
                "requested_line_count": len(candidate), "older_context_summary": summary,
                "recent_confirmed_context": context["recent"],
                "immutable_rows_inside_selection": context["anchors"],
                "preceding_processed_rows": processed_tail, "following_three_rows": following,
                "original_target_rows": [
                    mask_cast_composition_rows([row], start_index=originals.index(row) + 1)[0]
                    for row in candidate
                ],
                "nearby_other_speakers": [
                    {"speaker": row.get("characterId"), "text": row.get("text", "")}
                    for row in originals[max(0, originals.index(candidate[0]) - 2):last + 2]
                    if str(row.get("characterId", "")) != character_id
                ],
                "simultaneous_requirement": "指定なし",
            }

        batch, _fit = largest_fitting_prefix(pending, build_user, system)
        call_index += 1
        progress = ((group_index - 1) + (processed_count + len(batch)) / max(1, len(originals))) / group_total
        update(
            job_id, status="generating", phase="dialogue",
            message=f"{group_index}/{group_total} シーン・{target_cast[0].get('name', '')}（{processed_count + len(batch)}/{len(originals)}行）を確認しています…",
            overallProgress=min(90, 10 + 80 * progress),
        )
        generation_context = build_user(batch)
        try:
            raw = call(
                request, job_id, system=system, user=generation_context,
                max_tokens=output_reservation(len(batch)), temperature=0.35,
                path=debug / f"group-{group_index}-cast-{id_to_alias.get(character_id)}-{call_index}.txt",
                feature="script-assistant-dialogue",
            )
        except deps.GenerationCancelled:
            raise
        except Exception as error:
            if rows or reviewed_count:
                return rows, reviewed_count, f"後続区間を確認できなかったため部分提案です: {error}"
            raise
        parsed = parse_dialogue_protocol(
            raw, allowed_speakers=set(request.character_ids), speaker_aliases=alias_to_id,
        ).get("lines", [])
        accepted = direct_rows(request, parsed, originals)
        changes, reviewed = cast_composition_changes(request.operation, accepted, originals)
        rows.extend(changes)
        reviewed_count += reviewed
        processed_tail = _processed_tail(processed_tail, batch, changes)
        processed_count += len(batch)
        pending = pending[len(batch):]
    return rows, reviewed_count, ""

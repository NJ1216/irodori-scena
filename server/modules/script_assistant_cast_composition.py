from __future__ import annotations

import re
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps

PLACEHOLDER = re.compile(r"\[EMOJI_(\d+)\]")


def _emoji_runs(value: str) -> list[tuple[int, str]]:
    runs: list[tuple[int, str]] = []
    plain_index = 0
    index = 0
    while index < len(value):
        if not deps.is_emoji_component(value[index]):
            plain_index += 1
            index += 1
            continue
        end = index + 1
        while end < len(value) and deps.is_emoji_component(value[end]):
            end += 1
        runs.append((plain_index, value[index:end]))
        index = end
    return runs


def mask_cast_composition_rows(rows: list[dict[str, Any]], *, start_index: int = 1) -> list[dict[str, Any]]:
    masked: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows, start_index):
        text = str(row.get("text", ""))
        offset = 0
        parts: list[str] = []
        for emoji_index, (_position, emoji) in enumerate(_emoji_runs(text), 1):
            found = text.find(emoji, offset)
            parts.extend((text[offset:found], f"[EMOJI_{emoji_index}]"))
            offset = found + len(emoji)
        parts.append(text[offset:])
        masked.append({**row, "rewrite_id": f"R{row_index}", "text": "".join(parts)})
    return masked


def restore_cast_composition_emojis(candidate: str, source: str) -> str:
    runs = _emoji_runs(source)
    plain_candidate = PLACEHOLDER.sub("", deps.strip_draft_emojis(candidate)).strip()
    if not runs:
        return plain_candidate
    placeholders = [int(match.group(1)) for match in PLACEHOLDER.finditer(candidate)]
    if placeholders == list(range(1, len(runs) + 1)):
        clean = deps.strip_draft_emojis(candidate).strip()
        return PLACEHOLDER.sub(lambda match: runs[int(match.group(1)) - 1][1], clean)
    source_plain_length = max(1, len(deps.strip_draft_emojis(source)))
    insertions: dict[int, list[str]] = {}
    for position, emoji in runs:
        target = round(position / source_plain_length * len(plain_candidate))
        insertions.setdefault(target, []).append(emoji)
    result = plain_candidate
    for position in sorted(insertions, reverse=True):
        result = result[:position] + "".join(insertions[position]) + result[position:]
    return result


def cast_composition_original(
    raw: dict[str, Any], index: int, parsed_count: int, originals: list[dict[str, Any]],
) -> dict[str, Any] | None:
    rewrite_id = str(raw.get("development_id", ""))
    if match := re.fullmatch(r"R(\d+)", rewrite_id):
        position = int(match.group(1)) - 1
        return originals[position] if 0 <= position < len(originals) else None
    if parsed_count == len(originals) and index < len(originals):
        return originals[index]
    return None


def rewrite_original(raw: dict[str, Any], originals: list[dict[str, Any]]) -> dict[str, Any] | None:
    rewrite_id = str(raw.get("development_id", ""))
    if match := re.fullmatch(r"R(\d+)", rewrite_id):
        position = int(match.group(1)) - 1
        return originals[position] if 0 <= position < len(originals) else None
    return None


def validate_cast_composition_target(groups: list[dict[str, Any]], request: Any) -> None:
    if request.operation != "cast-compose":
        return
    selected_speakers = {
        str(line.get("characterId", "")) for group in groups for line in group["originalLines"]
    }
    if not selected_speakers.issubset(set(request.character_ids)):
        raise HTTPException(status_code=422, detail="キャスト構成の対象行と対象キャストが一致しません。")


def cast_composition_changes(
    operation: str, accepted: list[dict[str, Any]], originals: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    if operation != "cast-compose":
        return accepted, 0
    by_id = {str(item.get("id", "")): item for item in originals}
    order = {str(item.get("id", "")): index for index, item in enumerate(originals)}
    unique: dict[str, dict[str, Any]] = {}
    for row in accepted:
        original_id = str(row.get("originalLineId", ""))
        if original_id in by_id and original_id not in unique:
            unique[original_id] = row
    reviewed = sorted(unique.values(), key=lambda row: order[str(row["originalLineId"])])
    changed = [
        row for row in reviewed
        if row["text"] != str(by_id.get(str(row.get("originalLineId", "")), {}).get("text", ""))
    ]
    return changed, len(reviewed)


def cast_composition_warnings(operation: str, reviewed: int, target: int, has_rows: bool) -> list[str]:
    if operation != "cast-compose":
        return []
    warnings = [] if has_rows else ["キャスト設定から逸脱している提案対象はありませんでした。"]
    if reviewed < target:
        warnings.append(f"対象{target}行のうち{reviewed}行を確認できました。")
    return warnings

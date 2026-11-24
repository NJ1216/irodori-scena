"""Validation and application of pronunciation spans owned by one dialogue line."""

from server.app_deps import Any
from server.registry import deps


def apply_line_pronunciations(
    text: str,
    pronunciations: Any,
    character_id: str,
    active_character_ids: set[str] | None = None,
    dictionary_entries: list[dict[str, Any]] | None = None,
) -> str:
    if not isinstance(pronunciations, list):
        return deps.apply_pronunciation_dictionary(text, character_id, active_character_ids, dictionary_entries)
    valid: list[tuple[int, int, str]] = []
    for item in pronunciations:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        source, reading = item.get("text"), item.get("reading")
        typed = isinstance(start, int) and isinstance(end, int) and isinstance(source, str) and isinstance(reading, str)
        if not typed or start < 0 or end <= start or end > len(text) or not reading or "\n" in reading:
            continue
        if text[start:end] != source or any(start < other_end and other_start < end for other_start, other_end, _ in valid):
            continue
        valid.append((start, end, reading))
    valid.sort(key=lambda item: item[0])
    output: list[str] = []
    cursor = 0
    for start, end, reading in valid:
        output.append(deps.apply_pronunciation_dictionary(text[cursor:start], character_id, active_character_ids, dictionary_entries))
        output.append(reading)
        cursor = end
    output.append(deps.apply_pronunciation_dictionary(text[cursor:], character_id, active_character_ids, dictionary_entries))
    return "".join(output)


def resolve_line_pronunciations(
    text: str, pronunciations: Any, character_id: str,
    active_character_ids: set[str], dictionary_entries: list[dict[str, Any]],
) -> tuple[str, set[str]]:
    """Apply line-local spans first and retain global IDs used elsewhere."""
    if not isinstance(pronunciations, list):
        return deps.resolve_pronunciation_dictionary(text, character_id, active_character_ids, dictionary_entries)
    valid: list[tuple[int, int, str]] = []
    for item in pronunciations:
        if not isinstance(item, dict):
            continue
        start, end, source, reading = item.get("start"), item.get("end"), item.get("text"), item.get("reading")
        if not (isinstance(start, int) and isinstance(end, int) and isinstance(source, str) and isinstance(reading, str)):
            continue
        if start < 0 or end <= start or end > len(text) or not reading or "\n" in reading or text[start:end] != source:
            continue
        if any(start < other_end and other_start < end for other_start, other_end, _ in valid):
            continue
        valid.append((start, end, reading))
    valid.sort()
    output: list[str] = []
    used: set[str] = set()
    cursor = 0
    for start, end, reading in valid:
        resolved, ids = deps.resolve_pronunciation_dictionary(text[cursor:start], character_id, active_character_ids, dictionary_entries)
        output.extend((resolved, reading))
        used.update(ids)
        cursor = end
    resolved, ids = deps.resolve_pronunciation_dictionary(text[cursor:], character_id, active_character_ids, dictionary_entries)
    output.append(resolved)
    used.update(ids)
    return "".join(output), used


deps.register(__name__, ["apply_line_pronunciations", "resolve_line_pronunciations"])

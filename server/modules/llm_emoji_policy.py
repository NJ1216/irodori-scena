from __future__ import annotations

from server.app_deps import Callable
from server.registry import deps

ANCHOR_VARIANT_TRANSLATION = str.maketrans({",": "、", "，": "、", ".": "。", "．": "。", "　": " "})
EMOJI_MAX_PER_ANCHOR = 3


def _normalize_anchor(value: str) -> str:
    return value.translate(ANCHOR_VARIANT_TRANSLATION)


def is_emoji_component(character: str) -> bool:
    codepoint = ord(character)
    return 126976 <= codepoint <= 129791 or 8960 <= codepoint <= 11263 or character in {"\u200d", "︎", "️"}


def _allowed_emoji_at(value: str, index: int, allowed: set[str]) -> str | None:
    return next((emoji for emoji in sorted(allowed, key=len, reverse=True) if value.startswith(emoji, index)), None)


def _split_allowed_emoji_sequence(value: str, allowed: set[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(value):
        emoji = _allowed_emoji_at(value, index, allowed)
        if emoji is None:
            raise ValueError("not an allowed emoji sequence")
        result.append(emoji)
        index += len(emoji)
    return result


def _ends_with_emoji_sequence(value: str, sequence: list[str]) -> bool:
    """Whether an identical expression is already immediately before an anchor."""
    return bool(sequence) and value.endswith("".join(sequence))


def _normalized_proposed_emoji_sequence(value: str, allowed: set[str]) -> str | None:
    """Keep a syntactically emoji-only proposal, capped at one anchor's limit."""
    result: list[str] = []
    index = 0
    while index < len(value):
        emoji = _allowed_emoji_at(value, index, allowed)
        if emoji:
            if len(result) < EMOJI_MAX_PER_ANCHOR:
                result.append(emoji)
            index += len(emoji)
        elif is_emoji_component(value[index]):
            index += 1
        else:
            return None
    return "".join(result)


def filter_llm_proposed_emojis(value: object, *, allowed: set[str] | None = None) -> str:
    """Keep only catalog-approved emoji supplied by an LLM, never source text."""
    text = str(value)
    permitted = allowed if allowed is not None else deps.IRODORI_EMOJIS
    result: list[str] = []
    index = 0
    consecutive_emojis = 0
    while index < len(text):
        match = _allowed_emoji_at(text, index, permitted)
        if match:
            if consecutive_emojis < EMOJI_MAX_PER_ANCHOR:
                result.append(match)
            consecutive_emojis += 1
            index += len(match)
        elif is_emoji_component(text[index]):
            index += 1
        else:
            result.append(text[index])
            consecutive_emojis = 0
            index += 1
    return "".join(result)


def strip_irodori_expression_emojis(value: object) -> str:
    """Remove catalog expression emoji from existing source text only on explicit removal."""
    text = str(value)
    for emoji in sorted(deps.IRODORI_EMOJIS, key=len, reverse=True):
        text = text.replace(emoji, "")
    return text


def apply_llm_emoji_anchor_proposals(
    source: str,
    value: str,
    allowed: set[str],
    *,
    normalize_anchor: Callable[[str], str] = _normalize_anchor,
) -> str | None:
    """Apply valid proposed anchors, dropping only unapproved new emoji."""
    insertions: dict[int, list[str]] = {}
    for item in (part.strip() for part in value.split(";") if part.strip()):
        emoji, separator, anchor = item.partition("@")
        if not separator or not anchor:
            return None
        proposed = _normalized_proposed_emoji_sequence(emoji, allowed)
        if proposed is None:
            return None
        if not proposed:
            continue
        occurrence = 1
        if "#" in anchor:
            possible_anchor, possible_count = anchor.rsplit("#", 1)
            if possible_count.isdigit() and int(possible_count) > 0:
                anchor, occurrence = possible_anchor, int(possible_count)
        normalized_source = normalize_anchor(source)
        normalized_anchor = normalize_anchor(anchor)
        start = -1
        search_from = 0
        for _ in range(occurrence):
            start = normalized_source.find(normalized_anchor, search_from)
            if start < 0:
                return None
            search_from = start + len(normalized_anchor)
        proposed_sequence = _split_allowed_emoji_sequence(proposed, allowed)
        current = insertions.setdefault(start, [])
        # A repeated record is a common small-model formatting mistake. Repetition
        # intended for performance must be expressed inside one emoji sequence,
        # for example `🐢🐢@語句`, so preserve that sequence exactly but do not
        # add the same record twice.
        if current[-len(proposed_sequence):] == proposed_sequence:
            continue
        if not current and _ends_with_emoji_sequence(source[:start], proposed_sequence):
            continue
        current.extend(proposed_sequence)
        insertions[start] = current[:EMOJI_MAX_PER_ANCHOR]
    result = source
    for position in reversed(sorted(insertions)):
        result = result[:position] + "".join(insertions[position]) + result[position:]
    return result


def apply_llm_emoji_annotations(
    text_value: object,
    annotations_value: object,
    *,
    enabled: bool,
    allowed: set[str] | None = None,
) -> str:
    """Apply legacy structured annotations through the shared LLM policy."""
    text = strip_irodori_expression_emojis(text_value).strip()
    if not enabled or not text or not isinstance(annotations_value, list):
        return text
    permitted = (allowed if allowed is not None else set(deps.IRODORI_EMOJIS)).intersection(deps.IRODORI_EMOJIS)
    grouped: dict[tuple[str, int], list[str]] = {}
    for raw in annotations_value:
        if not isinstance(raw, dict):
            continue
        emoji = str(raw.get("emoji", ""))
        placement = str(raw.get("placement", ""))
        target = strip_irodori_expression_emojis(raw.get("target", "")).strip()
        if emoji not in permitted:
            continue
        if placement == "line_start":
            anchor = text
        elif placement == "before_phrase" and target:
            anchor = target
        elif placement == "line_end" and emoji in deps.TAIL_EVENT_EMOJIS:
            anchor = ""
        else:
            continue
        if placement == "line_end":
            if not text.endswith(emoji):
                text += emoji
            continue
        try:
            occurrence = max(1, int(raw.get("occurrence", 1)))
        except (TypeError, ValueError):
            occurrence = 1
        group = grouped.setdefault((anchor, occurrence), [])
        if len(group) < EMOJI_MAX_PER_ANCHOR:
            group.append(emoji)
    proposals = [
        f"{''.join(emojis)}@{anchor}{f'#{occurrence}' if occurrence > 1 else ''}"
        for (anchor, occurrence), emojis in grouped.items()
    ]
    return apply_llm_emoji_anchor_proposals(text, ";".join(proposals), permitted) or text


deps.register(
    __name__,
    [
        "EMOJI_MAX_PER_ANCHOR",
        "apply_llm_emoji_annotations",
        "apply_llm_emoji_anchor_proposals",
        "filter_llm_proposed_emojis",
        "is_emoji_component",
        "strip_irodori_expression_emojis",
    ],
)

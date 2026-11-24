"""Pure text and number predicates shared by draft dialogue assembly."""
from __future__ import annotations

import math
from typing import Any

from server.registry import deps


def _strict_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def is_inner_monologue_text(value: str) -> bool:
    text = str(value).strip()
    return len(text) >= 2 and text.startswith("（") and text.endswith("）")


def is_draft_japanese_writing_character(character: str) -> bool:
    """Return whether a character is an ordinary hiragana, katakana, or kanji glyph."""
    codepoint = ord(character)
    return (
        12353 <= codepoint <= 12438
        or 12449 <= codepoint <= 12538
        or 13312 <= codepoint <= 19903
        or (19968 <= codepoint <= 40959)
        or (63744 <= codepoint <= 64255)
        or (character == "々")
    )


def is_minor_draft_text_correction(source_text: str, performed_text: str) -> bool:
    """Allow only one local, equal-length one/two-glyph Japanese substitution.

    This intentionally rejects insertions, deletions, punctuation, whitespace,
    numerals, emoji, and separate changes. It is a narrow typo-correction path,
    not a general text-normalization rule.
    """
    if source_text == performed_text:
        return False
    prefix_length = 0
    while (
        prefix_length < len(source_text)
        and prefix_length < len(performed_text)
        and (source_text[prefix_length] == performed_text[prefix_length])
    ):
        prefix_length += 1
    suffix_length = 0
    source_remaining = len(source_text) - prefix_length
    performed_remaining = len(performed_text) - prefix_length
    while (
        suffix_length < source_remaining
        and suffix_length < performed_remaining
        and (
            source_text[len(source_text) - suffix_length - 1] == performed_text[len(performed_text) - suffix_length - 1]
        )
    ):
        suffix_length += 1
    source_end = len(source_text) - suffix_length if suffix_length else len(source_text)
    performed_end = len(performed_text) - suffix_length if suffix_length else len(performed_text)
    replaced_source = source_text[prefix_length:source_end]
    replaced_performed = performed_text[prefix_length:performed_end]
    return (
        len(replaced_source) == len(replaced_performed)
        and 1 <= len(replaced_source) <= 2
        and all((is_draft_japanese_writing_character(character) for character in replaced_source))
        and all((is_draft_japanese_writing_character(character) for character in replaced_performed))
    )


deps.register(
    __name__,
    [
        "_strict_float",
        "is_draft_japanese_writing_character",
        "is_inner_monologue_text",
        "is_minor_draft_text_correction",
    ],
)

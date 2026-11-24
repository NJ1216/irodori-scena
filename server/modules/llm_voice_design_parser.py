from __future__ import annotations

import json
import unicodedata
from typing import Callable

from server.registry import deps

LABELS = {
    "VOICE_KEYWORDS",
    "AGE",
    "GENDER",
    "PITCH",
    "QUALITY",
    "STYLE",
    "NOTES",
    "BASELINE_TEXT",
    "NORMAL_TEXT",
    "JOY_TEXT",
    "ANGER_TEXT",
    "SORROW_TEXT",
    "DELIGHT_TEXT",
}


def is_voice_design_emoji_tail_character(character: str) -> bool:
    return (
        character.isspace()
        or character == "\u20e3"
        or deps.is_emoji_component(character)
        or unicodedata.category(character) == "So"
    )


def strip_trailing_voice_design_emojis(value: str) -> str:
    terminal_punctuation = frozenset("。！？!?、，．…ー〜）〕］」』〉》")
    cleaned_lines = []
    for line in value.splitlines():
        suffix_start = len(line)
        while suffix_start and line[suffix_start - 1] in terminal_punctuation:
            suffix_start -= 1
        end, keycap_tail = suffix_start, False
        while end:
            character = line[end - 1]
            if character == "\u20e3":
                keycap_tail = True
            elif keycap_tail and character in "#*0123456789":
                pass
            elif not is_voice_design_emoji_tail_character(character):
                break
            end -= 1
        cleaned_lines.append(f"{line[:end]}{line[suffix_start:]}")
    return "\n".join(cleaned_lines).strip()


def collapse_adjacent_voice_design_sentences(value: str) -> str:
    lines: list[str] = []
    for line in value.splitlines():
        sentence = line.strip()
        if sentence and (not lines or lines[-1] != sentence):
            lines.append(sentence)
    return "\n".join(lines)


def is_japanese_voice_design_caption(value: str) -> bool:
    japanese_count = sum("\u3040" <= character <= "\u30ff" or "\u3400" <= character <= "\u9fff" for character in value)
    latin_count = sum("A" <= character <= "Z" or "a" <= character <= "z" for character in value)
    return japanese_count > 0 and latin_count <= max(12, japanese_count * 2)


def clean_voice_design_text(key: str, value: str, *, allowed: set[str] | None = None) -> str:
    cleaned = collapse_adjacent_voice_design_sentences(
        strip_trailing_voice_design_emojis(deps.filter_llm_proposed_emojis(value, allowed=allowed))
    )
    return deps.strip_draft_emojis(cleaned).strip() if key == "NORMAL_TEXT" else cleaned


def _filter_caption(values: dict[str, str]) -> dict[str, str] | None:
    if deps.prohibited_negative_tts_caption_reason(values.get("VOICE_KEYWORDS", "")):
        values.pop("VOICE_KEYWORDS", None)
    return values or None


def parse_voice_design_response(
    raw: object, *, text: Callable[[object], str], lines: Callable[[object], list[str]]
) -> dict[str, str] | None:
    source = text(raw)
    try:
        parsed = json.loads(source)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        values = {
            key.upper(): value.strip()
            for key, value in parsed.items()
            if isinstance(key, str) and isinstance(value, str)
        }
        if values and set(values).issubset(LABELS):
            return _filter_caption(values)
        keywords, sample = parsed.get("voice_keywords"), parsed.get("sample_text")
        if isinstance(keywords, str) and isinstance(sample, str):
            return _filter_caption(
                {
                    "VOICE_KEYWORDS": keywords.strip(),
                    **{label: sample.strip() for label in LABELS if label != "VOICE_KEYWORDS"},
                }
            )
    source_lines = lines(raw)
    if len(source_lines) == 1:
        collapsed = [part.strip() for part in source_lines[0].split("|")]
        while collapsed and not collapsed[-1]:
            collapsed.pop()
        if (
            len(collapsed) in {3, 4}
            and collapsed[0] == "VOICE_KEYWORDS"
            and all(collapsed[1:])
            and not any(part in {"VOICE_KEYWORDS", "SAMPLE_TEXT"} for part in collapsed[1:])
        ):
            sample = "\n".join(collapsed[2:])
            return _filter_caption(
                {"VOICE_KEYWORDS": collapsed[1], **{label: sample for label in LABELS if label != "VOICE_KEYWORDS"}}
            )
    candidates: dict[str, set[str]] = {}
    for line in source_lines:
        parts = [part.strip() for part in line.split("|", 1)]
        if len(parts) == 2 and parts[0] in LABELS and parts[1]:
            candidates.setdefault(parts[0], set()).add(parts[1])
    return _filter_caption({key: next(iter(items)) for key, items in candidates.items() if len(items) == 1})


deps.register(__name__, ["parse_voice_design_response", "clean_voice_design_text"])

from __future__ import annotations

import re
import math

from server.registry import deps


_THEME_LENGTH_ANCHORS = (
    (1, 180, 260), (3, 250, 350), (10, 400, 600),
    (30, 900, 1300), (60, 1600, 2200),
)


def draft_theme_length_bounds(target_minutes: float) -> tuple[int, int]:
    """Return the useful outline density for the requested spoken duration."""
    lower, upper = _THEME_LENGTH_ANCHORS[-1][1:]
    for left, right in zip(_THEME_LENGTH_ANCHORS, _THEME_LENGTH_ANCHORS[1:], strict=False):
        if target_minutes <= right[0]:
            ratio = (target_minutes - left[0]) / (right[0] - left[0])
            lower = round(left[1] + (right[1] - left[1]) * ratio)
            upper = round(left[2] + (right[2] - left[2]) * ratio)
            break
    return lower, upper


def draft_outline_policy(target_minutes: float, theme: str) -> dict[str, object]:
    """Choose how the planner should adapt author input to the available duration."""
    lower, upper = draft_theme_length_bounds(target_minutes)
    input_characters = len("".join(str(theme).split()))
    if input_characters < lower:
        mode = "expand"
        instruction = (
            "短い作者入力を核として保ち、尺を支えられる新しい出来事、判断、反応、感情変化を補う。"
            "同じ状況や設定の言い換えで量を増やさず、各展開で物語を一段ずつ前へ進める。"
        )
    elif input_characters > upper:
        mode = "compress"
        instruction = (
            "作者入力は尺に対して過密なので、明示された必須条件、因果、出来事の順序、否定条件、目的、結末を保持し、"
            "説明、例示、反復、枝葉を統合して尺内で成立する一本の進行へ圧縮する。全項目を順番に台詞化しない。"
        )
    else:
        mode = "preserve"
        instruction = (
            "作者入力の情報量は尺に適している。条件と順序を保ち、因果と感情の推移を整理して構成へ変換する。"
        )
    return {
        "mode": mode,
        "input_characters": input_characters,
        "recommended_theme_characters": {"minimum": lower, "maximum": upper},
        "story_chapters": max(1, min(8, math.ceil(target_minutes / 3))),
        "instruction": instruction,
    }


def _split_theme_text(text: str, limit: int = 240) -> list[str]:
    """Split long author prose at sentence boundaries without dropping content."""
    sentences = [item for item in re.split(r"(?<=[。！？!?])", text) if item]
    parts: list[str] = []
    current = ""
    for sentence in sentences or [text]:
        while len(sentence) > limit:
            if current:
                parts.append(current)
                current = ""
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        if current and len(current) + len(sentence) > limit:
            parts.append(current)
            current = sentence
        else:
            current += sentence
    if current:
        parts.append(current)
    return parts


def draft_theme_sections(theme: str) -> list[dict[str, str]]:
    """Retain author headings, paragraphs and bullets as deterministic plan evidence."""
    blocks: list[tuple[str, str]] = []
    current_title = ""
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append((current_title, " ".join(paragraph)))
            paragraph.clear()

    for raw in str(theme).replace("\r\n", "\n").split("\n"):
        value = raw.strip()
        if not value:
            flush_paragraph()
            continue
        heading = re.match(r"^(?:#{1,6}\s*|第?\d+[章部幕][：:\s]*)(.+)$", value)
        if heading:
            flush_paragraph()
            current_title = heading.group(1).strip() or value
            blocks.append((current_title, value))
            continue
        bullet = re.match(r"^(?:[-*・]\s*|\d+[.)）]\s*)(.+)$", value)
        if bullet:
            flush_paragraph()
            blocks.append((current_title, bullet.group(1).strip()))
            continue
        paragraph.append(value)
    flush_paragraph()
    sections: list[dict[str, str]] = []
    for title, text in blocks:
        for part in _split_theme_text(text):
            sections.append({"id": f"S{len(sections) + 1}",
                             "title": title or f"入力{len(sections) + 1}", "text": part,
                             "title_source": "author" if title else "internal"})
    return sections or [{"id": "S1", "title": "テーマ", "text": str(theme).strip() or "指定された場面",
                         "title_source": "internal"}]


def draft_author_ending(theme: str, sections: list[dict[str, str]] | None = None,
                       quotes: list[str] | None = None) -> dict[str, str] | None:
    """Accept only an unambiguous verbatim ending quote returned by planning."""
    source_sections = sections or draft_theme_sections(theme)
    candidates = set(quote for quote in quotes or [] if isinstance(quote, str) and quote.strip())
    if len(candidates) != 1:
        return None
    quote = candidates.pop()
    owners = [section for section in source_sections if quote in section["text"]]
    if theme.count(quote) != 1 or len(owners) != 1:
        return None
    return {"id": "AUTHOR_ENDING", "section_id": owners[0]["id"], "text": quote}


deps.register(__name__, [
    "draft_author_ending", "draft_outline_policy", "draft_theme_length_bounds", "draft_theme_sections",
])

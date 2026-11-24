"""Normalize unambiguous planning headings without rewriting creative text."""
from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

_FIELDS = {
    "目的": "OBJECTIVE", "開始状態": "OPENING", "展開": "BEAT",
    "終了状態": "CLOSING", "新規性": "NOVELTY", "継続条件": "CONTINUITY",
}


def normalize_plan_lines(lines: Iterable[str]) -> Iterator[str]:
    cast_block = False
    for value in lines:
        chapter = re.fullmatch(r"CHAPTER\s+(\d+)\s*[:：]\s*(.*)", value)
        if chapter:
            cast_block = False
            yield f"CHAPTER|{chapter[1]}|{chapter[2]}"
            continue
        if re.fullmatch(r"CAST_CONTEXT\s*[:：]\s*", value):
            cast_block = True
            continue
        if cast_block:
            cast = re.fullmatch(r"([A-Z]{1,3})\s*[:：]\s*(.+)", value)
            if cast:
                # This variant supplies an introduction, not a separate role.
                yield f"CAST_CONTEXT|{cast[1]}||{cast[2]}"
                continue
            cast_block = False
        field = re.match(r"^(目的|開始状態|展開|終了状態|新規性|継続条件)\s*[:：]\s*(.*)$", value)
        yield f"{_FIELDS[field[1]]}|{field[2]}" if field else value

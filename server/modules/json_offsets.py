"""Decode one value with an absolute end offset for the existing LLM parsers."""
from __future__ import annotations

from json import JSONDecoder
from typing import Any


def decode_at(decoder: JSONDecoder, content: str, start: int) -> tuple[Any, int]:
    return decoder.raw_decode(content, start)

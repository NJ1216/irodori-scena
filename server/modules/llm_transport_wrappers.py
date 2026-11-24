"""Deterministic removal of leaked model transport wrappers."""

from __future__ import annotations

import re

from server.registry import deps


def unwrap_harmony_final(text: str) -> str:
    """Keep the last explicit final message when Harmony tokens leak."""
    markers = list(re.finditer(r"<\|channel\|>\s*final\s*<\|message\|>", text, re.IGNORECASE))
    if not markers:
        return text
    final = text[markers[-1].end():]
    return re.sub(r"\s*<\|(?:end|return)\|>\s*$", "", final, flags=re.IGNORECASE).strip()
deps.register(__name__, ["unwrap_harmony_final"])

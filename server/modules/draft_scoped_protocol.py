"""Retain explicit source ownership and completion in non-schema responses."""
from __future__ import annotations

import re

from server.draft_protocol import parse_dialogue_protocol


def parse_scoped_dialogue(content: str, **options):
    lines, buffer = [], []
    source = None

    def flush(complete=False):
        parsed = parse_dialogue_protocol("\n".join(buffer), **options)["lines"]
        for line in parsed:
            if source:
                line["development_id"] = source
                if complete:
                    line["source_complete"] = True
        lines.extend(parsed)
        buffer.clear()

    for row in content.splitlines():
        marker = re.fullmatch(r"\s*::(SOURCE|SOURCE_END)\|([A-Za-z0-9_.-]{1,64})\s*", row)
        if marker:
            kind, identity = marker.groups()
            flush(kind == "SOURCE_END" and identity == source)
            source = identity if kind == "SOURCE" else None
        else:
            buffer.append(row)
    flush()
    return {"lines": lines}

from __future__ import annotations

import time

from server.registry import deps
from server.draft_protocol import parse_dialogue_protocol


def estimate_streamed_text_characters(content: str) -> int:
    """Count decoded characters in JSON ``text`` strings, including an open one."""
    total = index = 0
    while index < len(content):
        if content[index] != '"':
            index += 1
            continue
        index += 1
        key: list[str] = []
        escaped = False
        while index < len(content):
            char = content[index]
            index += 1
            if escaped:
                key.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                break
            else:
                key.append(char)
        else:
            break
        cursor = index
        while cursor < len(content) and content[cursor].isspace():
            cursor += 1
        if "".join(key) != "text" or cursor >= len(content) or content[cursor] != ":":
            continue
        cursor += 1
        while cursor < len(content) and content[cursor].isspace():
            cursor += 1
        if cursor >= len(content) or content[cursor] != '"':
            continue
        cursor += 1
        while cursor < len(content):
            char = content[cursor]
            cursor += 1
            if char == '"':
                break
            if char == "\\" and cursor < len(content):
                escape = content[cursor]
                cursor += 1
                if escape == "u" and cursor + 4 <= len(content):
                    cursor += 4
            total += 1
        index = cursor
    return total


def draft_stream_progress_reporter(
    job_id: str,
    accepted: int,
    aliases: dict[str, str],
    target: int,
    message: str = "台本の続きを書いています",
):
    last_published_at = 0.0

    def report(streamed: str) -> None:
        nonlocal last_published_at
        now = time.monotonic()
        if last_published_at and now - last_published_at < 1.0:
            return
        last_published_at = now
        preview = parse_dialogue_protocol(streamed, allowed_speakers=set(aliases.values()))
        spoken = deps.spoken_dialogue_count(preview)
        estimated = accepted + max(spoken, estimate_streamed_text_characters(streamed))
        deps.update_draft_job(
            job_id, receivedCharacters=len(streamed), receivedRecords=len(preview.get("lines", [])),
            message="応答を確認中", estimatedGeneratedCharacters=estimated,
            progressUpdatedAt=deps.now_ms(),
        )
        deps.advance_draft_progress(
            job_id,
            generated_characters=accepted,
        )

    return report


deps.register(__name__, ["draft_stream_progress_reporter", "estimate_streamed_text_characters"])

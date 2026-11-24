from __future__ import annotations

from typing import Any

from server.registry import deps

DIRECTION_CHUNK_SIZE = 30
DIRECTION_CONTEXT_SIZE = 3


def direction_chunk_size(profile: dict[str, Any] | None = None, *, experimental: bool | None = None) -> int:
    """Choose the validated bounded size for the job capability."""
    del experimental
    if not isinstance(profile, dict):
        return DIRECTION_CHUNK_SIZE
    size = profile.get("directionChunkSize")
    return size if size in deps.DIRECTION_CHUNK_CANDIDATES else DIRECTION_CHUNK_SIZE


def direction_input_token_estimate(
    rows: list[dict[str, Any]], before: list[dict[str, Any]], after: list[dict[str, Any]],
    cast_context: list[dict[str, Any]] | None = None,
) -> int:
    characters = 1400 + sum(
        len(str(value)) for item in [*before, *rows, *after]
        for value in item.values() if value not in (None, "")
    )
    characters += sum(len(str(value)) for item in cast_context or [] for value in item.values())
    return max(1024, int(characters * 1.15) + 256)


deps.register(__name__, ["DIRECTION_CHUNK_SIZE", "DIRECTION_CONTEXT_SIZE", "direction_chunk_size",
                         "direction_input_token_estimate"])

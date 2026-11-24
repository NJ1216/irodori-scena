from __future__ import annotations

from pathlib import Path
from typing import Any
import json


def target_context_for_memory(memory_gib: float | None) -> int:
    if memory_gib is not None and memory_gib >= 128:
        return 32768
    if memory_gib is not None and memory_gib >= 64:
        return 16384
    if memory_gib is not None and memory_gib >= 32:
        return 8192
    return 4096


def configured_model_limit(selected: dict[str, Any]) -> int | None:
    values: list[int] = []
    setting = (selected.get("settings") or {}).get("contextLimit")
    if isinstance(setting, int) and not isinstance(setting, bool):
        values.append(setting)
    path = (selected.get("localMetadata") or {}).get("path")
    if path:
        try:
            config = json.loads((Path(str(path)) / "config.json").read_text(encoding="utf-8"))
            text_config = config.get("text_config") if isinstance(config, dict) else None
            candidates = (
                text_config.get("max_position_embeddings") if isinstance(text_config, dict) else None,
                config.get("max_position_embeddings") if isinstance(config, dict) else None,
            )
            values.extend(
                value
                for value in candidates
                if isinstance(value, int) and not isinstance(value, bool) and value >= 4096
            )
        except (OSError, ValueError, TypeError):
            pass
    return min(values) if values else None

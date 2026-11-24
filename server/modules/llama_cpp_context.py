from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, BinaryIO

from server.registry import deps

CONTEXT_TIERS = (32768, 16384, 8192)
SAFETY_BYTES = 2 * 1024**3
KV_BYTES_PER_TOKEN = 128 * 1024


class GgufMetadataError(ValueError):
    pass


def _read_exact(source: BinaryIO, size: int) -> bytes:
    value = source.read(size)
    if len(value) != size:
        raise GgufMetadataError("GGUFメタデータが途中で切れています。")
    return value


def _integer(source: BinaryIO, size: int, *, signed: bool = False) -> int:
    return int.from_bytes(_read_exact(source, size), "little", signed=signed)


def _string(source: BinaryIO) -> str:
    size = _integer(source, 8)
    if size > 16 * 1024**2:
        raise GgufMetadataError("GGUFメタデータの文字列が大きすぎます。")
    try:
        return _read_exact(source, size).decode("utf-8")
    except UnicodeDecodeError as error:
        raise GgufMetadataError("GGUFメタデータの文字列が不正です。") from error


def _value(source: BinaryIO, value_type: int, *, depth: int = 0) -> Any:
    if depth > 4:
        raise GgufMetadataError("GGUFメタデータの配列が深すぎます。")
    sizes = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    if value_type == 8:
        return _string(source)
    if value_type == 9:
        item_type, count = _integer(source, 4), _integer(source, 8)
        if count > 10_000_000:
            raise GgufMetadataError("GGUFメタデータの配列が大きすぎます。")
        return [_value(source, item_type, depth=depth + 1) for _ in range(count)]
    size = sizes.get(value_type)
    if size is None:
        raise GgufMetadataError(f"未対応のGGUFメタデータ型です: {value_type}")
    raw = _read_exact(source, size)
    if value_type in {6, 12}:
        return struct.unpack("<f" if value_type == 6 else "<d", raw)[0]
    return int.from_bytes(raw, "little", signed=value_type in {1, 3, 5, 11})


def read_gguf_context_limit(path: Path) -> int | None:
    """Read only GGUF header metadata; tensor payloads are never loaded."""
    with path.open("rb") as source:
        if _read_exact(source, 4) != b"GGUF":
            raise GgufMetadataError("GGUFファイルの識別子が不正です。")
        version = _integer(source, 4)
        if version not in {2, 3}:
            raise GgufMetadataError(f"未対応のGGUFバージョンです: {version}")
        _integer(source, 8)  # tensor count
        metadata_count = _integer(source, 8)
        if metadata_count > 1_000_000:
            raise GgufMetadataError("GGUFメタデータ件数が大きすぎます。")
        values: dict[str, Any] = {}
        for _ in range(metadata_count):
            key = _string(source)
            value_type = _integer(source, 4)
            value = _value(source, value_type)
            if key == "general.architecture" or key.endswith(".context_length"):
                values[key] = value
    architecture = values.get("general.architecture")
    context = values.get(f"{architecture}.context_length") if isinstance(architecture, str) else None
    return context if isinstance(context, int) and not isinstance(context, bool) and context > 0 else None


def model_context_limit(metadata: dict[str, Any]) -> int | None:
    value = metadata.get("modelContextLimit")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    files = metadata.get("files") or ([metadata["path"]] if metadata.get("path") else [])
    return read_gguf_context_limit(Path(str(files[0]))) if files else None


def available_memory_bytes(backend: str) -> int | None:
    snapshot = deps.memory_snapshot()
    if backend == "cuda" and snapshot.get("kind") == "split":
        value = (snapshot.get("vram") or {}).get("availableBytes")
    elif snapshot.get("kind") == "split":
        value = (snapshot.get("ram") or {}).get("availableBytes")
    else:
        value = snapshot.get("availableBytes")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def select_context_size(metadata: dict[str, Any], backend: str, manual_limit: int | None = None,
                        *, available_bytes: int | None = None) -> int:
    model_limit = model_context_limit(metadata)
    hard_limits = [value for value in (manual_limit, model_limit) if isinstance(value, int) and not isinstance(value, bool)]
    ceiling = min([32768, *hard_limits])
    candidates = [tier for tier in CONTEXT_TIERS if tier <= ceiling]
    if not candidates:
        raise MemoryError(f"モデルまたは手動上限のContext {ceiling:,} は最小割当 8,192 を満たしません。")
    memory = available_memory_bytes(backend) if available_bytes is None else available_bytes
    if memory is None:
        return candidates[-1]
    # GGUF disk size is not a CUDA VRAM requirement: llama.cpp may offload
    # layers to system RAM. Let its fit pass make the authoritative decision.
    if backend == "cuda":
        return candidates[0]
    model_bytes = metadata.get("diskBytes")
    if not isinstance(model_bytes, int) or isinstance(model_bytes, bool):
        return candidates[-1]
    usable = memory - model_bytes - SAFETY_BYTES
    for tier in candidates:
        if usable >= tier * KV_BYTES_PER_TOKEN:
            return tier
    raise MemoryError(
        f"{backend.upper()}メモリが不足しています。モデル {model_bytes / 1024**3:.1f} GiB と"
        f"安全余白 2.0 GiBを除くと、Context 8,192 を確保できません。"
    )


def fallback_contexts(selected: int) -> list[int]:
    return [tier for tier in CONTEXT_TIERS if tier <= selected]


deps.register(__name__, ["available_memory_bytes", "fallback_contexts", "model_context_limit",
                         "read_gguf_context_limit", "select_context_size"])

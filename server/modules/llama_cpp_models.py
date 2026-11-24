from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps

SHARD = re.compile(r"^(?P<stem>.+)-(?P<index>\d{5})-of-(?P<count>\d{5})\.gguf$", re.IGNORECASE)


def inspect_gguf_files(files: list[str]) -> None:
    if not files:
        raise FileNotFoundError("GGUFモデルの対象ファイルがありません。")
    for value in files:
        path = Path(value)
        with path.open("rb") as source:
            header = source.read(24)
        if len(header) != 24 or header[:4] != b"GGUF" or int.from_bytes(header[4:8], "little") not in {2, 3}:
            raise ValueError(f"GGUFファイルのヘッダーが不正です: {path.name}")


def _variant(files: list[Path]) -> dict[str, Any]:
    first = files[0]
    match = SHARD.match(first.name)
    name = match.group("stem") if match else first.stem
    from server.modules.llama_cpp_context import GgufMetadataError, read_gguf_context_limit
    try:
        context_limit = read_gguf_context_limit(first)
    except (OSError, GgufMetadataError):
        context_limit = None
    return {"id": "gguf-" + hashlib.sha256("\n".join(str(path) for path in files).encode()).hexdigest()[:24],
            "displayName": name, "path": str(first), "files": [str(path) for path in files],
            "shardCount": len(files), "diskBytes": sum(path.stat().st_size for path in files),
            "format": "GGUF", "modelContextLimit": context_limit,
            "inferredTags": [{"kind": "compatibility", "value": "GGUF"}]}


def scan_gguf_folder(path_value: str, *, max_files: int = 10_000) -> dict[str, Any]:
    root = Path(path_value).expanduser()
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise HTTPException(422, "GGUFモデルのフォルダが見つかりません。")
    files: list[Path] = []
    limited = False
    with os.scandir(root) as entries:
        for entry in entries:
            if len(files) >= max_files:
                limited = True
                break
            if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".gguf"):
                files.append(Path(entry.path).resolve())
    groups: dict[str, list[tuple[int, int, Path]]] = {}
    singles: list[Path] = []
    for path in sorted(files):
        if match := SHARD.match(path.name):
            groups.setdefault(match.group("stem").casefold(), []).append(
                (int(match.group("index")), int(match.group("count")), path))
        else:
            singles.append(path)
    variants = [_variant([path]) for path in singles]
    incomplete = []
    for name, shards in groups.items():
        counts = {count for _index, count, _path in shards}
        expected = next(iter(counts)) if len(counts) == 1 else 0
        indexes = [index for index, _count, _path in shards]
        if expected and indexes == list(range(1, expected + 1)):
            variants.append(_variant([path for _index, _count, path in shards]))
        else:
            incomplete.append({"displayName": name, "expectedShards": expected, "foundShards": len(shards)})
    return {"models": variants, "limited": limited, "ggufFound": bool(files), "incomplete": incomplete}


def register_external_gguf_model(path_value: str) -> dict[str, Any]:
    selected = Path(path_value).expanduser()
    if not selected.is_absolute() or not selected.is_file() or selected.is_symlink():
        raise HTTPException(422, "GGUFモデルが見つかりません。")
    scan = scan_gguf_folder(str(selected.parent))
    model = next((item for item in scan["models"] if selected.resolve() in map(Path, item["files"])), None)
    if model is None:
        raise HTTPException(422, "分割GGUFが不足しているか、候補を特定できません。")
    card = deps.register_local_llm_card(model["id"], source="external", metadata={
        **model, "engine": "llama.cpp", "fingerprint": hashlib.sha256(
            "\n".join(f"{path}:{path.stat().st_size}:{path.stat().st_mtime_ns}" for path in map(Path, model["files"])).encode()
        ).hexdigest(),
    })
    return {"card": card, "model": model}


deps.register(__name__, ["register_external_gguf_model", "scan_gguf_folder"])

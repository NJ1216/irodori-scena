"""Device-local LoRA storage; project containers retain references only."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from fastapi import HTTPException
from server.registry import deps


def lora_root() -> Path:
    return deps.TTS_ASSETS_ROOT / "lora"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def owned_path(kind: str, identifier: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise HTTPException(422, "LoRA ID が不正です。")
    return lora_root() / kind / identifier


def read_record(kind: str, identifier: str) -> dict:
    try:
        return json.loads((owned_path(kind, identifier) / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise HTTPException(404, "LoRA データが見つかりません。") from error

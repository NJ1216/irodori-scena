"""Freeze a validated registered adapter for a new, independent training job."""
from pathlib import Path
import shutil

from fastapi import HTTPException

from server.modules.lora_assets import resolve_lora_asset
from server.modules.lora_storage import digest, read_record
from server.modules.lora_validation import validate_adapter


def freeze_adapter(identifier: str, directory: Path, runtime: dict) -> dict:
    record = read_record("adapters", identifier)
    if record.get("archived"):
        raise HTTPException(422, "登録解除したLoRAは追加学習できません。登録を戻してください。")
    resolved = resolve_lora_asset({**record, "assetId": identifier})
    source = Path(resolved["path"])
    target = directory / "source-adapter"
    target.mkdir()
    for name, key in (("adapter_config.json", "configHash"), ("adapter_model.safetensors", "weightsHash")):
        candidate = source / name
        if candidate.is_symlink() or not candidate.is_file():
            raise HTTPException(422, "追加学習元のLoRAが不正です。")
        shutil.copyfile(candidate, target / name)
        if digest(target / name) != record[key]:
            raise HTTPException(409, "追加学習元のLoRAが変更されています。")
    try:
        validate_adapter(target, Path(runtime["checkpoint"]))
    except (OSError, ValueError) as error:
        raise HTTPException(422, "追加学習元のLoRAを検証できません。") from error
    return {"assetId": identifier, "configHash": record["configHash"], "weightsHash": record["weightsHash"]}

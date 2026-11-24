"""Immutable, copied adapter assets with complete byte identities."""
from __future__ import annotations
import hashlib
import shutil
import uuid
from pathlib import Path
from fastapi import HTTPException
from server.modules.lora_runtime import MODEL_REPO, MODEL_REVISION, base_checkpoint, BASE_SHA256
from server.modules.lora_storage import digest, lora_root, owned_path, read_record, write_json
from server.modules.lora_validation import validate_adapter
from server.registry import deps


def adapter_hash(directory: Path) -> str:
    value = hashlib.sha256()
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        with (directory / name).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(chunk)
    return value.hexdigest()


def import_adapter(path: str, name: str, memo: str = "", *, base_model_repo=MODEL_REPO, base_model_revision=MODEL_REVISION) -> dict:
    if (base_model_repo, base_model_revision) != (MODEL_REPO, MODEL_REVISION):
        raise HTTPException(422, "初期対応は公式 v4.1 Small の固定版のみです。")
    source = Path(path).expanduser()
    if not source.is_absolute() or not source.is_dir() or not name.strip():
        raise HTTPException(422, "LoRA フォルダの絶対パスと管理名が必要です。")
    identifier = uuid.uuid4().hex
    target = owned_path("adapters", identifier)
    target.mkdir(parents=True)
    try:
        for filename in ("adapter_config.json", "adapter_model.safetensors"):
            candidate = source / filename
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError("Adapter requires regular config and safetensors files")
            limit = 65536 if filename.endswith("json") else 512 * 1024 * 1024
            if candidate.stat().st_size > limit:
                raise ValueError("Adapter file exceeds supported size")
            shutil.copyfile(candidate, target / filename)
        checkpoint = base_checkpoint()
        if digest(checkpoint) != BASE_SHA256:
            raise ValueError("Base checkpoint identity mismatch")
        validation = validate_adapter(target, checkpoint)
        record = {"id": identifier, "assetId": identifier, "name": name, "memo": memo,
                  "adapterHash": adapter_hash(target), "configHash": digest(target / "adapter_config.json"),
                  "weightsHash": digest(target / "adapter_model.safetensors"), "baseModelRepo": MODEL_REPO,
                  "baseModelRevision": MODEL_REVISION, "baseModelHash": BASE_SHA256, "validation": validation}
        write_json(target / "record.json", record)
        return record
    except (HTTPException, OSError, ValueError) as error:
        shutil.rmtree(target, ignore_errors=True)
        if isinstance(error, HTTPException):
            raise
        raise HTTPException(422, f"LoRA を検証できません: {error}") from error


def list_adapters(*, archived: bool = False, include_archived: bool = False) -> list[dict]:
    records = []
    for path in sorted((lora_root() / "adapters").glob("*/record.json")):
        try:
            record = read_record("adapters", path.parent.name)
            if include_archived or (record.get("archived") is True) == archived:
                records.append(record)
        except HTTPException:
            continue
    return records


def resolve_lora_asset(reference: dict) -> dict:
    try:
        record = read_record("adapters", reference["assetId"])
        path = owned_path("adapters", record["id"])
        identity = ("adapterHash", "baseModelRepo", "baseModelRevision")
        if any(reference.get(key) != record.get(key) for key in identity):
            raise ValueError("Saved adapter identity mismatch")
        if record["baseModelRepo"] != MODEL_REPO or record["baseModelRevision"] != MODEL_REVISION:
            raise ValueError("Unsupported adapter base model")
        if record.get("baseModelHash") != BASE_SHA256:
            raise ValueError("Adapter base model hash mismatch")
        if adapter_hash(path) != record["adapterHash"]:
            raise ValueError("Adapter bytes changed")
        return {**{key: record[key] for key in (*identity, "configHash", "weightsHash")}, "path": str(path)}
    except (HTTPException, OSError, KeyError, ValueError) as error:
        raise HTTPException(409, "LoRA 資産が欠損・変更されています。再登録または無効化してください。") from error


deps.register(__name__, ["resolve_lora_asset"])

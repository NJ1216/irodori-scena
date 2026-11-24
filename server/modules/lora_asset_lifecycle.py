"""Registered adapter metadata, legacy archive, and guarded permanent deletion."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any

from fastapi import HTTPException

from server.modules.lora_assets import resolve_lora_asset
from server.modules.lora_deletion_files import delete_adapter_files
from server.modules.lora_resource_guard import LOCK, require_runtime_available
from server.modules.lora_storage import owned_path, read_record, write_json
from server.modules.pronunciation_dictionary import dictionary_transaction
from server.registry import deps

_METADATA_LOCK = threading.RLock()
SCOPE = "current_project_and_global_casts"


def _references(item: dict[str, Any], identifier: str) -> bool:
    mix = item.get("loraMix")
    if isinstance(mix, dict):
        return any(entry.get("assetId") == identifier for entry in mix.get("entries", []))
    reference = item.get("lora")
    return isinstance(reference, dict) and reference.get("assetId") == identifier


@dictionary_transaction
def adapter_usage(identifier: str) -> dict[str, Any]:
    read_record("adapters", identifier)
    with deps.PROJECT_ROOT_LOCK:
        project = deps.read_project()
        characters = [(item, str(item.get("scope") or "project")) for item in project.get("characters", []) if isinstance(item, dict)]
        characters.extend((item, "global") for item in deps.read_global_characters() if isinstance(item, dict))
        casts = {(str(item.get("id", "")), scope): {"id": str(item.get("id", "")), "name": str(item.get("name", "")), "scope": scope}
                 for item, scope in characters if _references(item, identifier)}
        takes = [{"lineId": str(line.get("id", "")), "takeId": str(take.get("id", "")), "characterId": str(take.get("characterId") or line.get("characterId", ""))}
                 for scene in project.get("scenes", []) for line in scene.get("lines", [])
                 for take in line.get("takes", []) if _references(take, identifier)]
        return {"scope": SCOPE, "projectId": str(project.get("id", "")), "casts": list(casts.values()),
                "takes": takes, "takeCount": len(takes), "otherSavedProjectsChecked": False}


@contextmanager
def _mutation_admission():
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, "生成基盤が使用中です。完了後にLoRAの登録を変更してください。")
    try:
        require_runtime_available()
        yield
    finally:
        LOCK.release()


def archive_adapter(identifier: str) -> dict[str, Any]:
    with _mutation_admission():
        return _archive_locked(identifier)


@dictionary_transaction
def _archive_locked(identifier: str) -> dict[str, Any]:
    with deps.PROJECT_ROOT_LOCK, _METADATA_LOCK:
        record = read_record("adapters", identifier)
        if record.get("archived") is True:
            return record
        usage = adapter_usage(identifier)
        if usage["casts"] or usage["takes"]:
            names = "、".join(item["name"] for item in usage["casts"])
            message = f"このLoRAは使用中です。キャスト: {names or 'なし'}、現在のプロジェクトのTake: {usage['takeCount']}件。設定とTakeを確認してください。"
            raise HTTPException(409, {"code": "lora_asset_in_use", "message": message, "usage": usage})
        record.update(archived=True, archivedAt=int(time.time() * 1000))
        write_json(owned_path("adapters", identifier) / "record.json", record)
        return record


def restore_adapter(identifier: str) -> dict[str, Any]:
    with _mutation_admission(), _METADATA_LOCK:
        record = read_record("adapters", identifier)
        if record.get("archived") is not True:
            return record
        # Restoration cannot put a broken or tampered asset back into the selector.
        resolve_lora_asset(record)
        record["archived"] = False
        record.pop("archivedAt", None)
        write_json(owned_path("adapters", identifier) / "record.json", record)
        return record


def update_adapter(identifier: str, name: str, memo: str) -> dict:
    if not name.strip():
        raise HTTPException(422, "LoRA名を入力してください。")
    with _METADATA_LOCK:
        record = read_record("adapters", identifier)
        record.update(name=name, memo=memo)
        write_json(owned_path("adapters", identifier) / "record.json", record)
        return record


@dictionary_transaction
def delete_adapter(identifier: str) -> dict[str, Any]:
    with _mutation_admission(), deps.PROJECT_ROOT_LOCK, _METADATA_LOCK:
        record = read_record("adapters", identifier)
        usage = adapter_usage(identifier)
        if usage["casts"] or usage["takes"]:
            raise HTTPException(409, {"code": "lora_asset_in_use", "message": "このLoRAはキャストまたはTakeで使用中のため削除できません。", "usage": usage})
        try:
            delete_adapter_files(identifier)
        except OSError as error:
            raise HTTPException(409, "LoRAのファイルを削除できませんでした。") from error
        return {**record, "deleted": True}

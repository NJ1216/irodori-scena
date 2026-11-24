"""Persistent model/runtime ownership and serialization of registry mutations."""
from __future__ import annotations

import threading
import sys
from functools import wraps
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps

LOCK = threading.RLock()


def serialized(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with LOCK:
            return function(*args, **kwargs)
    return guarded


def recommended_id() -> str:
    from server.modules.omlx_environment import _recommended_id
    return _recommended_id()


def migrate_bindings(registry: dict[str, Any]) -> None:
    if sys.platform == "win32":
        status = deps.llama_cpp_runtime_status(deps.selected_backend())
        runtime_id = f"llama.cpp-{status['version']}-{status['backend']}"
        for card in registry["cards"]:
            if card.get("source") in {"managed", "external"}:
                card.setdefault("runtimeId", runtime_id)
                if isinstance(card.get("localMetadata"), dict):
                    card["localMetadata"].setdefault("engine", "llama.cpp")
            else:
                card.pop("runtimeId", None)
        return
    from server.modules.omlx_environment import _read_registry, _normalize_registry
    runtimes = _read_registry()
    _normalize_registry(runtimes)
    previous = runtimes.get("activeRuntimeId")
    for card in registry["cards"]:
        if card.get("source") in {"managed", "external"}:
            card.setdefault("runtimeId", previous or recommended_id())
            if isinstance(card.get("localMetadata"), dict):
                card["localMetadata"]["omlxVersion"] = card["runtimeId"]
        else:
            card.pop("runtimeId", None)


def runtime_item(runtime_id: str) -> dict[str, Any] | None:
    from server.modules.omlx_environment import _registry
    from pathlib import Path
    item = next((x for x in _registry()["runtimes"] if x["id"] == runtime_id or runtime_id in x.get("aliases", [])), None)
    if item and (Path(item["path"]) / ".ready").is_file():
        return item
    return None


def model_runtime(model_id: str) -> str:
    card = next((x for x in deps.read_llm_registry()["cards"]
                 if x.get("source") in {"managed", "external"} and x["modelId"] == model_id), None)
    if not card or not card.get("runtimeId"):
        raise HTTPException(409, "モデルの実行基盤を準備してください。")
    from server.modules.model_runtime_jobs import model_runtime_status
    state = model_runtime_status(card)
    job = state.get("job")
    if job and job["previousRuntimeId"] == card["runtimeId"] and job["state"] != "complete":
        raise HTTPException(409, "モデルの準備が未完了です。カードから再試行してください。")
    return card["runtimeId"]


def runtime_references(runtime_id: str) -> list[dict[str, str]]:
    from server.modules.omlx_environment import _registry
    item = next((x for x in _registry()["runtimes"] if x["id"] == runtime_id), {})
    identities = {runtime_id, *item.get("aliases", [])}
    return [{"id": x["id"], "displayName": x["displayName"]} for x in deps.read_llm_registry()["cards"]
            if x.get("runtimeId") in identities]


def local_processing() -> bool:
    return any(x["status"] == "running" and (x.get("runtimeId") or x.get("provider") in {"", "scena-local"})
               for x in deps.session_usage()["history"])


def require_idle() -> None:
    from server.modules.lora_resource_guard import require_runtime_available
    require_runtime_available()
    from server.modules.model_runtime_jobs import active_jobs
    if local_processing() or deps.llm_model_test_active() or active_jobs(verifying_only=True):
        raise HTTPException(409, "ローカルLLM処理中です。完了後に再試行してください。")


def deletion_reason(runtime_id: str) -> str | None:
    from server.modules import local_llm_runtime, omlx_environment
    from server.modules.model_runtime_jobs import active_jobs
    if runtime_references(runtime_id):
        return "登録モデルが使用しています。"
    if any(x.get("runtimeId") == runtime_id for x in active_jobs()):
        return "モデルの実行基盤を準備・確認中です。"
    job = omlx_environment._JOB
    if job.get("runtimeId") == runtime_id and job.get("state") in omlx_environment.BUSY:
        return "導入中です。"
    if local_llm_runtime.RUNTIME_ID == runtime_id and local_llm_runtime.local_llm_runtime_pid():
        return "ローカルLLMが使用中です。"
    return None


def require_generation_available(provider: str) -> None:
    from server.modules.lora_resource_guard import require_runtime_available
    require_runtime_available()
    if provider not in {"", "scena-local"}:
        return
    from server.modules.model_runtime_jobs import active_jobs
    if active_jobs(verifying_only=True) or deps.llm_model_test_active():
        raise HTTPException(409, "モデルの動作確認中です。完了後に生成してください。")


def require_load_available(model_id: str) -> None:
    from server.modules.lora_resource_guard import require_runtime_available
    require_runtime_available()
    from server.modules.model_runtime_jobs import active_jobs
    if any(x.get("threadId") != threading.get_ident() for x in active_jobs(verifying_only=True)):
        raise HTTPException(409, "実行基盤を確認中です。")
    from server.modules.llm_model_tests import MODEL_TESTS
    if any(x.get("threadId") != threading.get_ident() and x.get("localBusy") for x in MODEL_TESTS.values()):
        raise HTTPException(409, "モデルを動作確認中です。")
    operations = deps.session_usage()["history"]
    if any(x["status"] == "running" and (x.get("runtimeId") or x.get("provider") in {"", "scena-local"})
           and x.get("model") not in {"", model_id} for x in operations):
        raise HTTPException(409, "別のモデルでローカル処理中です。")


def require_card_removable(card_id: str) -> None:
    from server.modules.lora_resource_guard import require_runtime_available
    require_runtime_available()
    from server.modules.model_runtime_jobs import active_jobs
    from server.modules.huggingface_models import HF_DOWNLOADS
    preparing = any(x["cardId"] == card_id for x in active_jobs())
    downloading = any(x.get("cardId") == card_id and x["state"] not in {"complete", "failed", "cancelled"}
                      for x in HF_DOWNLOADS.values())
    if preparing or downloading or local_processing() or deps.llm_model_test_active(card_id):
        raise HTTPException(409, "モデルの取得・実行基盤の準備・ローカル処理を取消または完了してください。")

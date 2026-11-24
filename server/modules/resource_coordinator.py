from __future__ import annotations

import threading
import sys

from server.registry import deps
from server.modules.llm_runtime_binding import serialized
from server.modules.lora_resource_guard import require_runtime_available

RESOURCE_LOCK = threading.RLock()
MEMORY_OWNER: str | None = None
MEMORY_REASON = ""
LLM_RESIDENT = False
_OPERATION_GENERATION = 0
_OWNER_GENERATIONS = {"tts": 0, "llm": 0}


def memory_ownership() -> dict[str, str | None]:
    with RESOURCE_LOCK:
        state = {"owner": MEMORY_OWNER, "reason": MEMORY_REASON, "llmResident": LLM_RESIDENT}
    worker = deps.INFERENCE_WORKER
    state["ttsResident"] = bool(worker is not None and worker.poll() is None)
    return state


def _windows_exclusive() -> bool:
    return sys.platform == "win32"


def _can_retain_tts_for_builtin_llm() -> bool:
    """Fail closed unless current free memory covers the documented coexistence budget."""
    try:
        selected = deps.resolve_default_llm()
        if selected.get("provider") != "scena-local":
            return True
        total, available = deps.physical_memory()
        model_bytes = (selected.get("localMetadata") or {}).get("diskBytes")
        if not isinstance(total, int) or not isinstance(available, int) or not isinstance(model_bytes, int):
            return False
        guard = (selected.get("settings") or {}).get("memoryGuard", "safe")
        hot_cache = {"safe": 2, "balanced": 4, "aggressive": 8}.get(guard, 2) * 1024 ** 3
        mtp = deps.mtp_asset_status().get("diskBytes", 0) if (selected.get("settings") or {}).get("mtp") else 0
        if not isinstance(mtp, int):
            return False
        safety = max(8 * 1024 ** 3, int(total * 0.15))
        required = model_bytes + hot_cache + mtp + 2 * 1024 ** 3 + safety
        return available >= required
    except Exception:
        return False


def _reserve(owner: str) -> int:
    global _OPERATION_GENERATION
    with RESOURCE_LOCK:
        _OPERATION_GENERATION += 1
        _OWNER_GENERATIONS[owner] = _OPERATION_GENERATION
        return _OPERATION_GENERATION


def memory_generation(owner: str) -> int:
    with RESOURCE_LOCK:
        return _OWNER_GENERATIONS[owner]


def _complete(owner: str, reason: str, generation: int) -> None:
    global MEMORY_OWNER, MEMORY_REASON, LLM_RESIDENT
    with RESOURCE_LOCK:
        if generation != _OPERATION_GENERATION:
            return
        MEMORY_OWNER, MEMORY_REASON = owner, reason
        LLM_RESIDENT = owner == "llm"


@serialized
def acquire_llm_memory(reason: str) -> None:
    require_runtime_available()
    generation = _reserve("llm")
    if _windows_exclusive() or not _can_retain_tts_for_builtin_llm():
        deps.shutdown_inference_worker()
        deps.mark_tts_released("SCENA内蔵LLMの安全余裕を確保")
    _complete("llm", reason, generation)


@serialized
def acquire_tts_memory(reason: str, *, coexist: bool = False) -> None:
    require_runtime_available()
    generation = _reserve("tts")
    if not coexist:
        deps.release_windows_external_llm()
        deps.unload_local_llm()
    _complete("tts", reason, generation)


def release_memory(owner: str, *, generation: int | None = None) -> None:
    global MEMORY_OWNER, MEMORY_REASON, LLM_RESIDENT
    with RESOURCE_LOCK:
        if generation is not None and generation != _OWNER_GENERATIONS[owner]:
            return
        if MEMORY_OWNER == owner:
            MEMORY_OWNER, MEMORY_REASON = None, ""
        if owner == "llm":
            LLM_RESIDENT = False


deps.register(__name__, ["acquire_llm_memory", "acquire_tts_memory", "memory_ownership", "memory_generation", "release_memory"])

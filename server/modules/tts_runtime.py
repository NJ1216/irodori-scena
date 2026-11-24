from __future__ import annotations

import threading
import time
import sys
from typing import Any

from server.registry import deps

_LOCK = threading.RLock()
_EPOCH = 0
_LAST_INTERACTION = time.monotonic()
_CALIBRATION_IDLE_SECONDS = 1.5
_STATUS: dict[str, Any] = {
    "state": "stopped", "modelId": None, "stage": None, "message": None,
    "error": None, "releaseReason": None, "preparationReason": None,
    "updatedAt": int(time.time() * 1000),
}


def _selected_model_id() -> str | None:
    runtime = deps.selected_tts_runtime()
    model = runtime.get("model") if runtime else None
    return str(model.get("id")) if model and model.get("id") else None


def _set(**changes: Any) -> dict[str, Any]:
    with _LOCK:
        _STATUS.update(changes, updatedAt=int(time.time() * 1000))
        return dict(_STATUS)


def tts_runtime_status() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATUS)


def mark_tts_in_use(model_id: str | None) -> None:
    global _EPOCH
    with _LOCK:
        if _STATUS["state"] == "preparing":
            _EPOCH += 1
        _set(state="in-use", modelId=model_id, stage="generating", message="音声を生成中", error=None, releaseReason=None)


def mark_tts_ready(model_id: str | None) -> None:
    _set(state="ready", modelId=model_id, stage="ready", message="準備完了", error=None, releaseReason=None)
    if model_id:
        deps.start_cuda_calibration(model_id, lambda: _calibration_may_continue(model_id))


def _calibration_may_continue(model_id: str) -> bool:
    """Wait for UI quiet; stop when the runtime leaves ready, changes model, or the LLM owns memory."""
    while True:
        with _LOCK:
            if _STATUS["state"] != "ready" or _STATUS["modelId"] != model_id:
                return False
            remaining = _CALIBRATION_IDLE_SECONDS - (time.monotonic() - _LAST_INTERACTION)
        if deps.memory_ownership().get("owner") == "llm":
            return False
        if remaining <= 0:
            return True
        time.sleep(min(remaining, 0.1))


def mark_tts_released(reason: str) -> None:
    global _EPOCH
    with _LOCK:
        _EPOCH += 1
    _set(state="stopped", stage=None, message="LLM用に解放", error=None, releaseReason=reason)


def reset_tts_runtime(reason: str | None = None) -> None:
    global _EPOCH
    with _LOCK:
        _EPOCH += 1
    _set(state="stopped", modelId=_selected_model_id(), stage=None, message=None, error=None, releaseReason=reason)


def note_tts_interaction() -> None:
    global _LAST_INTERACTION
    with _LOCK:
        _LAST_INTERACTION = time.monotonic()


def _set_if_preparing(epoch: int, **changes: Any) -> bool:
    with _LOCK:
        if epoch != _EPOCH or _STATUS["state"] != "preparing":
            return False
        _set(**changes)
        return True


def _prepare(epoch: int, model_id: str, coexist: bool = False, startup: bool = False) -> None:
    try:
        if startup:
            if deps.active_draft_job() or deps.active_export_job() or deps.memory_ownership().get("owner") == "llm":
                _set_if_preparing(epoch, state="skipped", stage="skipped", message="TTS先読みを見送りました。",
                                  preparationReason="startup-resource-busy")
                return
            prepare, coexist, reason = _post_draft_policy()
            if not prepare or not coexist:
                _set_if_preparing(epoch, state="skipped", stage="skipped", message="TTS先読みを見送りました。", preparationReason=(
                    "startup-would-release-llm" if prepare else reason))
                return
            if not _set_if_preparing(epoch, preparationReason=reason):
                return
        with _LOCK:
            if epoch != _EPOCH or _STATUS["state"] != "preparing":
                return
            _set(stage="loading", message="モデル・Codec・tokenizerを読込中")
        deps.prepare_irodori_worker(coexist=coexist)
        with _LOCK:
            if epoch != _EPOCH or model_id != _selected_model_id():
                return
        mark_tts_ready(model_id)
    except Exception as error:  # surfaced through the status API; generation may retry normally
        with _LOCK:
            if epoch != _EPOCH:
                return
        _set(state="failed", stage="failed", message="準備失敗", error=str(getattr(error, "detail", error))[-1800:])


def _post_draft_policy() -> tuple[bool, bool, str]:
    """Return prepare/coexist/reason; unknown VRAM requirements fail closed."""
    if sys.platform != "win32":
        return True, True, "unified-memory-policy"
    runtime = deps.selected_tts_runtime() or {}
    required = (runtime.get("model") or {}).get("requiredVramBytes")
    snapshot = deps.fresh_memory_snapshot()
    vram = snapshot.get("vram") if snapshot.get("kind") == "split" else None
    total = (vram or {}).get("totalBytes")
    available = (vram or {}).get("availableBytes")
    if not all(isinstance(value, int) and value > 0 for value in (required, total, available)):
        return False, False, "vram-requirement-unverified"
    safety = max(1024 ** 3, int(total * 0.1))
    if available >= required + safety:
        return True, True, "coexistence-vram-available"
    selected = deps.resolve_default_llm()
    if selected.get("provider") == "scena-local":
        return True, False, "scena-llm-release-required"
    return False, False, "external-llm-retained-vram-insufficient"


def start_tts_prepare(*, after_draft: bool = False, startup: bool = False) -> dict[str, Any]:
    global _EPOCH
    model_id = _selected_model_id()
    with _LOCK:
        if model_id and _STATUS["modelId"] == model_id and _STATUS["state"] in {"preparing", "ready", "in-use"}:
            return dict(_STATUS)
        _EPOCH += 1
        epoch = _EPOCH
    if not model_id:
        if startup:
            return _set(state="stopped", modelId=None, stage=None, message=None,
                        error=None, releaseReason=None, preparationReason="no-selected-model")
        return _set(state="failed", modelId=None, stage="assets", message="準備失敗", error="音声モデルが選択されていません。", releaseReason=None)
    coexist, preparation_reason = False, None
    if after_draft:
        prepare, coexist, preparation_reason = _post_draft_policy()
        if not prepare:
            return _set(state="skipped", modelId=model_id, stage="skipped", message="TTS先読みを見送りました。",
                        error=None, releaseReason=None, preparationReason=preparation_reason)
    _set(state="preparing", modelId=model_id, stage="queued", message="準備中…", error=None,
         releaseReason=None, preparationReason=preparation_reason)
    threading.Thread(target=_prepare, args=(epoch, model_id, coexist, startup), daemon=True, name="tts-prepare").start()
    return tts_runtime_status()


deps.register(__name__, ["mark_tts_in_use", "mark_tts_ready", "mark_tts_released", "note_tts_interaction", "reset_tts_runtime", "start_tts_prepare", "tts_runtime_status"])

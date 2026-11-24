"""Training admission shares the existing outer runtime serialization boundary."""
from __future__ import annotations

import threading
from fastapi import HTTPException
from server.registry import deps
from server.modules.llm_runtime_binding import LOCK

_STATE_LOCK = threading.RLock()
_JOB_ID: str | None = None


def training_job_id() -> str | None:
    with _STATE_LOCK:
        return _JOB_ID


def require_runtime_available() -> None:
    # Call while holding LOCK at runtime admission. No resource work happens
    # under the short state lock, and no caller acquires LOCK under it.
    if training_job_id() is not None:
        raise HTTPException(409, {"code": "lora_training_busy", "message": "LoRA学習中です。完了または中断後に生成してください。"})


def _require_existing_work_idle() -> None:
    from server.modules.model_runtime_jobs import active_jobs
    if deps.INFERENCE_SYNTHESIS_LOCK.locked() or deps.active_export_job() or deps.active_draft_job():
        raise HTTPException(409, "音声生成・エクスポート・AI処理中です。完了後に学習してください。")
    if any(item["status"] == "running" for item in deps.session_usage()["history"]):
        raise HTTPException(409, "LLM処理中です。完了後に学習してください。")
    if deps.llm_model_test_active() or active_jobs(verifying_only=True):
        raise HTTPException(409, "モデルの動作確認中です。完了後に学習してください。")
    if deps.memory_ownership().get("llmResident"):
        raise HTTPException(409, "ローカルLLMが常駐しています。設定から解放してから学習してください。")


def reserve_training(job_id: str) -> None:
    global _JOB_ID
    if not LOCK.acquire(blocking=False):
        raise HTTPException(409, "生成基盤が使用中です。完了後に学習してください。")
    try:
        require_runtime_available()
        _require_existing_work_idle()
        # Release only the application's idle, owned inference worker.
        deps.shutdown_inference_worker()
        deps.release_memory("tts")
        deps.reset_tts_runtime("LoRA学習")
        with _STATE_LOCK:
            _JOB_ID = job_id
    finally:
        LOCK.release()


def release_training(job_id: str) -> None:
    global _JOB_ID
    with LOCK:
        with _STATE_LOCK:
            if _JOB_ID == job_id:
                _JOB_ID = None

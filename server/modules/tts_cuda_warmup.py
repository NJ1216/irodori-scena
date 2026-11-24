"""Background CUDA acceleration calibration of the common generation routes (Windows).

After the TTS runtime is ready, each common route is sent to the already-running
worker one at a time.  The worker skips routes it has already recorded, so a
fully calibrated machine sends twelve cheap requests and synthesizes nothing.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Callable

from server.registry import deps

CALIBRATION_TEXT = "これは高速化の確認に使う短いセリフです。"
CALIBRATION_CAPTION = "落ち着いて自然に話す。"
# Fast is the default quality, so it is calibrated first.
QUALITIES = ("fast", "quality", "turbo")
# A route slower than this keeps a generation waiting too long; later routes calibrate at first use.
ROUTE_BUDGET_SECONDS = 20.0
_RUNNING = threading.Lock()
_COMPLETED: set[str] = set()


def warmup_requests(capabilities: dict[str, Any]) -> list[dict[str, Any]]:
    """Requests with the same steps and schedule as real one-candidate generations."""
    if capabilities.get("flowParameterization") == "meanflow":
        return []
    requests = []
    for quality in QUALITIES:
        for reference in (False, True):
            for caption in (None, CALIBRATION_CAPTION):
                request = deps.synthesis_request(
                    text=CALIBRATION_TEXT, caption=caption, output=None, seed=0, ref_wav=None, quality=quality,
                    generation_settings=None, num_candidates=1, lora_adapter=None, capabilities=capabilities,
                )
                request.update(operation="calibrate", referenceProbe=reference)
                requests.append(request)
    return requests


def _generation_waiting() -> bool:
    return bool(deps.INFERENCE_SYNTHESIS_LOCK.locked())


def _wait_for_generation(should_continue: Callable[[], bool]) -> bool:
    """Let a running or waiting generation go first; False once calibration should stop."""
    while _generation_waiting():
        if not should_continue():
            return False
        time.sleep(0.1)
    return should_continue()


def _send(request: dict[str, Any]) -> str | None:
    """Send one route; return a stop reason, or None when the route was handled or yielded."""
    with deps.runtime_serialization(), deps.INFERENCE_WORKER_LOCK:
        if _generation_waiting():
            return "yield"
        worker = deps.INFERENCE_WORKER
        if worker is None or worker.poll() is not None:
            return "no-worker"
        deps.set_worker_background(worker, True)
        started = time.monotonic()
        try:
            deps.exchange_worker_request(worker, request)
        except Exception:  # noqa: BLE001 - background work must never surface as a failure.
            return "worker-error"
        return "slow-route" if time.monotonic() - started > ROUTE_BUDGET_SECONDS else None


def calibrate_common_routes(should_continue: Callable[[], bool]) -> dict[str, Any]:
    """Send each route while allowed; generations always go first."""
    if sys.platform != "win32":
        return {"state": "skipped", "reason": "not-windows"}
    pending = warmup_requests(deps.selected_model_capabilities() or {})
    calibrated = 0
    while pending:
        if not _wait_for_generation(should_continue):
            return {"state": "paused", "calibrated": calibrated}
        reason = _send(pending[0])
        if reason == "yield":
            continue
        if reason == "worker-error":
            # The exchange stopped the worker; report that instead of a stale "ready".
            deps.release_memory("tts")
            deps.reset_tts_runtime("calibration-worker-error")
        calibrated += reason in (None, "slow-route")
        if reason:
            return {"state": "stopped", "reason": reason, "calibrated": calibrated}
        pending.pop(0)
    return {"state": "complete", "calibrated": calibrated}


def start_cuda_calibration(model_id: str | None, should_continue: Callable[[], bool]) -> bool:
    """Start one background run unless one is active or this model finished in this session."""
    if not model_id or model_id in _COMPLETED or not _RUNNING.acquire(blocking=False):
        return False

    def work(selected: str) -> None:
        try:
            # Only a pause resumes in this session; a stop would repeat its cost or failure.
            if calibrate_common_routes(should_continue).get("state") != "paused":
                _COMPLETED.add(selected)
        finally:
            _RUNNING.release()

    threading.Thread(target=work, args=(model_id,), daemon=True, name="tts-cuda-calibration").start()
    return True


deps.register(__name__, ["calibrate_common_routes", "start_cuda_calibration"])

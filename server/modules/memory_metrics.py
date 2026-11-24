from __future__ import annotations

import os
import json
import sys
import threading
import time
from typing import Any

import psutil

from server.registry import deps


_TOTAL_MEMORY = int(psutil.virtual_memory().total)
_GPU_LOCK = threading.Lock()
_GPU_CACHED_AT = 0.0
_GPU_CACHED_VALUE: float | None = None
_GPU_IN_FLIGHT = False
_GPU_MEMORY_LOCK = threading.Lock()
_GPU_MEMORY_CACHED_AT = 0.0
_GPU_MEMORY_CACHED_VALUE: tuple[int, int] | None = None
_GPU_MEMORY_IN_FLIGHT = False
_GPU_RUNTIME_MEMORY_LOCK = threading.Lock()
_GPU_RUNTIME_MEMORY_CACHED_AT = 0.0
_GPU_RUNTIME_MEMORY_CACHED_VALUE: tuple[int | None, int | None] = (None, None)
_GPU_RUNTIME_MEMORY_IN_FLIGHT = False
GPU_UTILIZATION_CACHE_SECONDS = 1.0


def _accelerator_topology() -> dict[str, Any]:
    try:
        value = json.loads(os.getenv("SCENA_ACCELERATOR_TOPOLOGY", "{}"))
    except (TypeError, ValueError):
        return {"kind": "system-only", "adapterId": None, "dedicatedBytes": None, "dedicatedUsedBytes": None, "gpuUtilizationPercent": None}
    kind = value.get("kind")
    dedicated = value.get("dedicatedBytes")
    if kind == "unified":
        return {"kind": kind, "adapterId": value.get("adapterId"), "dedicatedBytes": None, "dedicatedUsedBytes": None, "gpuUtilizationPercent": value.get("gpuUtilizationPercent")}
    if kind == "dedicated" and isinstance(dedicated, int) and dedicated > 0:
        initial_used = value.get("dedicatedUsedBytes")
        return {"kind": kind, "adapterId": value.get("adapterId"), "dedicatedBytes": dedicated, "dedicatedUsedBytes": initial_used if isinstance(initial_used, int) else None, "gpuUtilizationPercent": value.get("gpuUtilizationPercent")}
    return {"kind": "system-only", "adapterId": None, "dedicatedBytes": None, "dedicatedUsedBytes": None, "gpuUtilizationPercent": None}


def _physical_memory() -> tuple[int | None, int | None]:
    """Return cached total and the current OS memory availability."""
    try:
        available = int(psutil.virtual_memory().available)
        return _TOTAL_MEMORY, min(_TOTAL_MEMORY, max(0, available))
    except (OSError, ValueError):
        return None, None


def physical_memory() -> tuple[int | None, int | None]:
    return _physical_memory()


def _measure_gpu_utilization() -> float | None:
    if sys.platform == "win32":
        from server.modules.windows_gpu import gpu_utilization
        return gpu_utilization()
    from server.modules.macos_gpu import gpu_utilization
    return gpu_utilization()


def _refresh_gpu_utilization() -> None:
    global _GPU_CACHED_AT, _GPU_CACHED_VALUE, _GPU_IN_FLIGHT
    try:
        value = _measure_gpu_utilization()
    except (OSError, ValueError):
        value = None
    with _GPU_LOCK:
        _GPU_CACHED_VALUE = value
        _GPU_CACHED_AT = time.monotonic() if value is not None else 0.0
        _GPU_IN_FLIGHT = False


def _gpu_utilization() -> float | None:
    global _GPU_IN_FLIGHT
    with _GPU_LOCK:
        cached = _GPU_CACHED_VALUE
        if _GPU_CACHED_AT > 0 and time.monotonic() - _GPU_CACHED_AT < GPU_UTILIZATION_CACHE_SECONDS:
            return cached
        if _GPU_IN_FLIGHT:
            return cached
        _GPU_IN_FLIGHT = True
    try:
        threading.Thread(target=_refresh_gpu_utilization, name="scena-gpu-utilization", daemon=True).start()
    except RuntimeError:
        with _GPU_LOCK:
            _GPU_IN_FLIGHT = False
    return cached


def _refresh_gpu_memory() -> None:
    global _GPU_MEMORY_CACHED_AT, _GPU_MEMORY_CACHED_VALUE, _GPU_MEMORY_IN_FLIGHT
    try:
        from server.modules.windows_gpu import gpu_memory
        value = gpu_memory()
    except (OSError, TypeError, ValueError):
        value = None
    with _GPU_MEMORY_LOCK:
        _GPU_MEMORY_CACHED_VALUE = value
        _GPU_MEMORY_CACHED_AT = time.monotonic() if value is not None else 0.0
        _GPU_MEMORY_IN_FLIGHT = False


def _gpu_memory() -> tuple[int, int] | None:
    global _GPU_MEMORY_IN_FLIGHT
    if sys.platform != "win32":
        return None
    with _GPU_MEMORY_LOCK:
        cached = _GPU_MEMORY_CACHED_VALUE
        if _GPU_MEMORY_CACHED_AT > 0 and time.monotonic() - _GPU_MEMORY_CACHED_AT < 5.0:
            return cached
        if _GPU_MEMORY_IN_FLIGHT:
            return cached
        _GPU_MEMORY_IN_FLIGHT = True
    try:
        threading.Thread(target=_refresh_gpu_memory, name="scena-gpu-memory", daemon=True).start()
    except RuntimeError:
        with _GPU_MEMORY_LOCK:
            _GPU_MEMORY_IN_FLIGHT = False
    return cached


def _process_tree(pid: int | None) -> set[int]:
    if not isinstance(pid, int) or pid <= 1:
        return set()
    try:
        process = psutil.Process(pid)
        return {pid, *(child.pid for child in process.children(recursive=True))}
    except (OSError, psutil.Error):
        return {pid}


def _measure_gpu_runtime_memory() -> tuple[int | None, int | None]:
    from server.modules.windows_gpu import gpu_process_memory

    usage = gpu_process_memory()
    worker = deps.INFERENCE_WORKER
    tts_pid = worker.pid if worker is not None and worker.poll() is None else None
    llm_pid = deps.local_llm_runtime_pid()
    llm = sum(usage.get(pid, 0) for pid in _process_tree(llm_pid))
    tts = sum(usage.get(pid, 0) for pid in _process_tree(tts_pid))
    return llm, tts


def _refresh_gpu_runtime_memory() -> None:
    global _GPU_RUNTIME_MEMORY_CACHED_AT, _GPU_RUNTIME_MEMORY_CACHED_VALUE, _GPU_RUNTIME_MEMORY_IN_FLIGHT
    try:
        value = _measure_gpu_runtime_memory()
    except (OSError, TypeError, ValueError, psutil.Error):
        value = (None, None)
    with _GPU_RUNTIME_MEMORY_LOCK:
        _GPU_RUNTIME_MEMORY_CACHED_VALUE = value
        _GPU_RUNTIME_MEMORY_CACHED_AT = time.monotonic()
        _GPU_RUNTIME_MEMORY_IN_FLIGHT = False


def _gpu_runtime_memory() -> tuple[int | None, int | None]:
    global _GPU_RUNTIME_MEMORY_CACHED_AT, _GPU_RUNTIME_MEMORY_IN_FLIGHT
    if sys.platform != "win32":
        return None, None
    with _GPU_RUNTIME_MEMORY_LOCK:
        cached = _GPU_RUNTIME_MEMORY_CACHED_VALUE
        cache_fresh = _GPU_RUNTIME_MEMORY_CACHED_AT > 0 and time.monotonic() - _GPU_RUNTIME_MEMORY_CACHED_AT < 5.0
        if cache_fresh or _GPU_RUNTIME_MEMORY_IN_FLIGHT:
            return cached
        _GPU_RUNTIME_MEMORY_IN_FLIGHT = True
    try:
        threading.Thread(
            target=_refresh_gpu_runtime_memory,
            name="scena-gpu-process-memory",
            daemon=True,
        ).start()
    except RuntimeError:
        with _GPU_RUNTIME_MEMORY_LOCK:
            _GPU_RUNTIME_MEMORY_CACHED_AT = time.monotonic()
            _GPU_RUNTIME_MEMORY_IN_FLIGHT = False
    return cached


def _model_runtime_pids() -> set[int]:
    worker = deps.INFERENCE_WORKER
    tts_pid = worker.pid if worker is not None and worker.poll() is None else None
    llm_pid = deps.local_llm_runtime_pid()
    return {pid for pid in (tts_pid, llm_pid) if isinstance(pid, int) and pid > 1}


def _scena_footprint() -> int | None:
    """Sum app RSS while keeping model-runtime processes in their own segments."""
    try:
        parent_pid = int(os.getenv("SCENA_PARENT_PID", "0"))
        root = psutil.Process(parent_pid if parent_pid > 1 and psutil.pid_exists(parent_pid) else os.getpid())
        excluded = _model_runtime_pids()
        processes = [root, *root.children(recursive=True)]
        return sum(
            process.memory_info().rss for process in processes
            if process.pid not in excluded and not any(parent.pid in excluded for parent in process.parents())
        )
    except (OSError, ValueError, psutil.Error):
        return None


def memory_snapshot() -> dict[str, Any]:
    total, available = _physical_memory()
    footprint = _scena_footprint()
    ownership = deps.memory_ownership()
    owner = ownership.get("owner")
    llm = deps.local_llm_metal_memory()
    tts = deps.tts_metal_memory()
    app_memory = max(0, footprint) if footprint is not None else None
    other: int | None = None
    if total is not None and available is not None and app_memory is not None and llm is not None and tts is not None:
        available = min(total, max(0, available))
        measured = min(total, max(0, app_memory) + max(0, llm) + max(0, tts))
        used = max(total - available, measured)
        available = total - used
        app_memory = min(used, max(0, app_memory))
        llm = min(used - app_memory, max(0, llm))
        tts = min(used - app_memory - llm, max(0, tts))
        other = used - llm - tts - app_memory
    topology = _accelerator_topology()
    gpu_utilization = _gpu_utilization() if topology["kind"] != "system-only" else None
    gpu_memory = _gpu_memory() if topology["kind"] == "dedicated" else None
    gpu_llm, gpu_tts = _gpu_runtime_memory() if topology["kind"] == "dedicated" else (None, None)
    gpu_used = gpu_memory[0] if gpu_memory else topology.get("dedicatedUsedBytes")
    common = {
        "gpuUtilizationPercent": gpu_utilization if gpu_utilization is not None else topology.get("gpuUtilizationPercent"),
        "sampledAt": int(time.time() * 1000),
    }
    if topology["kind"] == "dedicated":
        vram_total = topology["dedicatedBytes"]
        vram_used = min(vram_total, max(0, gpu_used)) if gpu_used is not None else None
        vram_available = vram_total - vram_used if vram_used is not None else None
        vram_other = (
            max(0, vram_used - gpu_llm - gpu_tts)
            if vram_used is not None and gpu_llm is not None and gpu_tts is not None
            else None
        )
        return {
            "kind": "split",
            "ram": {
                "totalBytes": total, "availableBytes": available, "otherUsedBytes": other,
                "scenaAppBytes": app_memory, "llmBytes": llm, "ttsBytes": tts,
            },
            "vram": {
                "totalBytes": vram_total, "availableBytes": vram_available,
                "otherUsedBytes": vram_other, "scenaAppBytes": 0,
                "llmBytes": gpu_llm, "ttsBytes": gpu_tts,
            },
            "acceleratorOwner": owner,
            **common,
        }
    return {
        "kind": "unified",
        "totalBytes": total,
        "availableBytes": available,
        "otherUsedBytes": other,
        "scenaAppBytes": app_memory,
        "llmBytes": llm,
        "ttsBytes": tts,
        "metalOwner": owner,
        "runningOwner": owner,
        "llmResident": bool(ownership.get("llmResident")),
        "ttsResident": bool(ownership.get("ttsResident")),
        **common,
    }


def fresh_memory_snapshot() -> dict[str, Any]:
    """Snapshot for a one-off decision: measure VRAM now, since the cache is empty until the first refresh ends."""
    global _GPU_MEMORY_IN_FLIGHT
    if sys.platform == "win32" and _accelerator_topology()["kind"] == "dedicated":
        with _GPU_MEMORY_LOCK:
            _GPU_MEMORY_IN_FLIGHT = True
        _refresh_gpu_memory()
    return memory_snapshot()


@deps.app.get("/api/system/memory")
def get_memory_snapshot() -> dict[str, Any]:
    return memory_snapshot()


deps.register(__name__, ["fresh_memory_snapshot", "memory_snapshot", "physical_memory"])

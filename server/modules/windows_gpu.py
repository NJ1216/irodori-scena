"""Lightweight NVIDIA telemetry for the shared footer sampling boundary."""
import atexit
import ctypes
import math
import re
import threading
import time


_NVML_LOCK = threading.Lock()
_NVML_LIBRARY = None
_NVML_HANDLES = None
_NVML_CACHED_AT = 0.0
_NVML_CACHED_VALUE = None


class _NvmlUtilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _NvmlMemory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


def _nvml_devices():
    global _NVML_LIBRARY, _NVML_HANDLES
    if _NVML_HANDLES is not None:
        return _NVML_LIBRARY, _NVML_HANDLES
    library = ctypes.WinDLL("nvml.dll")
    library.nvmlInit_v2.restype = ctypes.c_int
    library.nvmlDeviceGetCount_v2.argtypes = [ctypes.POINTER(ctypes.c_uint)]
    library.nvmlDeviceGetCount_v2.restype = ctypes.c_int
    library.nvmlDeviceGetHandleByIndex_v2.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
    library.nvmlDeviceGetHandleByIndex_v2.restype = ctypes.c_int
    library.nvmlDeviceGetUtilizationRates.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlUtilization)]
    library.nvmlDeviceGetUtilizationRates.restype = ctypes.c_int
    library.nvmlDeviceGetMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NvmlMemory)]
    library.nvmlDeviceGetMemoryInfo.restype = ctypes.c_int
    library.nvmlShutdown.restype = ctypes.c_int
    if library.nvmlInit_v2() != 0:
        raise OSError("nvmlInit_v2 failed")
    count = ctypes.c_uint()
    if library.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
        library.nvmlShutdown()
        raise OSError("nvmlDeviceGetCount_v2 failed")
    handles = []
    for index in range(count.value):
        handle = ctypes.c_void_p()
        if library.nvmlDeviceGetHandleByIndex_v2(index, ctypes.byref(handle)) == 0:
            handles.append(handle)
    _NVML_LIBRARY, _NVML_HANDLES = library, handles
    atexit.register(library.nvmlShutdown)
    return library, handles


def _read_nvml_samples() -> list[tuple[float, int, int]]:
    library, handles = _nvml_devices()
    samples = []
    for handle in handles:
        utilization, memory = _NvmlUtilization(), _NvmlMemory()
        if library.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(utilization)) != 0:
            continue
        if library.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) != 0:
            continue
        samples.append((float(utilization.gpu), int(memory.used), int(memory.total)))
    return samples


def _select_nvml_snapshot(samples: list[tuple[float, int, int]]) -> tuple[float, tuple[int, int]] | None:
    valid = [
        (min(100.0, max(0.0, utilization)), max(0, min(used, total)), total)
        for utilization, used, total in samples
        if math.isfinite(utilization) and total > 0
    ]
    if not valid:
        return None
    busiest = max(sample[0] for sample in valid)
    _, used, total = max(valid, key=lambda sample: sample[1])
    return busiest, (used, total)


def _nvml_snapshot() -> tuple[float, tuple[int, int]] | None:
    global _NVML_CACHED_AT, _NVML_CACHED_VALUE
    with _NVML_LOCK:
        now = time.monotonic()
        if now - _NVML_CACHED_AT < 0.5:
            return _NVML_CACHED_VALUE
        _NVML_CACHED_VALUE = _select_nvml_snapshot(_read_nvml_samples())
        _NVML_CACHED_AT = now
        return _NVML_CACHED_VALUE


def gpu_utilization() -> float | None:
    snapshot = _nvml_snapshot()
    return snapshot[0] if snapshot else None


def gpu_memory() -> tuple[int, int] | None:
    snapshot = _nvml_snapshot()
    return snapshot[1] if snapshot else None


def gpu_process_memory() -> dict[int, int]:
    """Read per-process dedicated GPU bytes through PDH without spawning a process."""
    import ctypes
    from ctypes import wintypes

    class ValueUnion(ctypes.Union):
        _fields_ = [("largeValue", ctypes.c_longlong), ("doubleValue", ctypes.c_double)]

    class CounterValue(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("status", wintypes.DWORD), ("value", ValueUnion)]

    class ValueItem(ctypes.Structure):
        _fields_ = [("name", wintypes.LPWSTR), ("value", CounterValue)]

    pdh = ctypes.WinDLL("pdh.dll")
    query, counter = wintypes.HANDLE(), wintypes.HANDLE()
    status = pdh.PdhOpenQueryW(None, 0, ctypes.byref(query))
    if status != 0:
        raise OSError(status, "PdhOpenQueryW failed")
    try:
        path = r"\GPU Process Memory(*)\Dedicated Usage"
        status = pdh.PdhAddEnglishCounterW(query, path, 0, ctypes.byref(counter))
        if status != 0:
            raise OSError(status, "PdhAddEnglishCounterW failed")
        status = pdh.PdhCollectQueryData(query)
        if status != 0:
            raise OSError(status, "PdhCollectQueryData failed")
        size, count = wintypes.DWORD(), wintypes.DWORD()
        status = pdh.PdhGetFormattedCounterArrayW(counter, 0x400, ctypes.byref(size), ctypes.byref(count), None)
        if status & 0xFFFFFFFF != 0x800007D2 or size.value == 0:
            raise OSError(status, "PdhGetFormattedCounterArrayW sizing failed")
        buffer = ctypes.create_string_buffer(size.value)
        status = pdh.PdhGetFormattedCounterArrayW(counter, 0x400, ctypes.byref(size), ctypes.byref(count), buffer)
        if status != 0:
            raise OSError(status, "PdhGetFormattedCounterArrayW failed")
        items = ctypes.cast(buffer, ctypes.POINTER(ValueItem))
        result: dict[int, int] = {}
        for index in range(count.value):
            match = re.match(r"pid_(\d+)_", items[index].name or "")
            if match and items[index].value.status == 0:
                pid = int(match.group(1))
                result[pid] = result.get(pid, 0) + max(0, int(items[index].value.largeValue))
        return result
    finally:
        pdh.PdhCloseQuery(query)

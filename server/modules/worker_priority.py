"""CPU priority of the Irodori-TTS worker on Windows.

A background load or calibration runs below normal priority so the window, script editing and the local
API keep the CPU; a generation restores normal priority as soon as it is requested, even while it still
waits for a running load to finish.
"""
from __future__ import annotations

import sys

import psutil

from server.registry import deps

_BELOW_NORMAL = getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", 0x4000)
_NORMAL = getattr(psutil, "NORMAL_PRIORITY_CLASS", 0x20)


def set_worker_background(worker, background: bool) -> None:
    pid = getattr(worker, "pid", None)
    if sys.platform != "win32" or pid is None or worker.poll() is not None:
        return
    try:
        psutil.Process(pid).nice(_BELOW_NORMAL if background else _NORMAL)
    except (psutil.Error, OSError):
        pass  # Priority is a courtesy; the worker keeps running either way.


deps.register(__name__, ["set_worker_background"])

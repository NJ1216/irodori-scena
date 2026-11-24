"""Production child-process boundary.

Every server-owned child is created without a console window on Windows.
The module intentionally mirrors the small ``subprocess`` surface used by the
server so callers cannot accidentally omit the platform contract.
"""
from __future__ import annotations

import os
import subprocess as _subprocess
from typing import Any

CREATE_NO_WINDOW = getattr(_subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _hidden(kwargs: dict[str, Any]) -> dict[str, Any]:
    if os.name == "nt":
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | CREATE_NO_WINDOW
    return kwargs


class Popen(_subprocess.Popen):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **_hidden(kwargs))


def run(*args: Any, **kwargs: Any):
    return _subprocess.run(*args, **_hidden(kwargs))


def check_output(*args: Any, **kwargs: Any):
    return _subprocess.check_output(*args, **_hidden(kwargs))


def check_call(*args: Any, **kwargs: Any):
    return _subprocess.check_call(*args, **_hidden(kwargs))


PIPE = _subprocess.PIPE
STDOUT = _subprocess.STDOUT
DEVNULL = _subprocess.DEVNULL
CalledProcessError = _subprocess.CalledProcessError
SubprocessError = _subprocess.SubprocessError
TimeoutExpired = _subprocess.TimeoutExpired

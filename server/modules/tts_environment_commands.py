"""Bounded diagnostics for managed inference-environment installation."""
import os
from server import subprocess_boundary as subprocess
import tempfile
import time

import psutil

from server.modules.tts_windows_quantized_variants import CUDA_MINIMUM_CAPABILITY, cuda_compute_capability


class EnvironmentCommandError(subprocess.CalledProcessError):
    def __str__(self):
        return f"推論環境の構築に失敗しました（終了コード {self.returncode}）。\n{self.stderr}"


def _stop_environment_command(process):
    try:
        root = psutil.Process(process.pid)
        owned = [*reversed(root.children(recursive=True)), root]
        for child in owned:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, remaining = psutil.wait_procs(owned, timeout=1)
        for child in remaining:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        _, remaining = psutil.wait_procs(remaining, timeout=1)
        if remaining:
            raise OSError("推論環境の構築プロセスを停止できませんでした。")
    except psutil.NoSuchProcess:
        pass
    except psutil.Error as error:
        raise OSError("推論環境の構築プロセスを停止できませんでした。") from error
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=1)


def _wait_environment_command(process, command, timeout, cancel):
    deadline = time.monotonic() + timeout
    while True:
        if cancel is not None and cancel.is_set():
            raise InterruptedError
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, timeout)
        try:
            return process.wait(timeout=min(0.1, remaining))
        except subprocess.TimeoutExpired:
            continue


def run_environment_command(command, *, timeout, env=None, cancel=None):
    if cancel is not None and cancel.is_set():
        raise InterruptedError
    # uv can produce large progress output; retain only its diagnostic tail in the job.
    with tempfile.TemporaryFile() as diagnostics:
        process = subprocess.Popen(command, env=env, stdout=diagnostics, stderr=diagnostics)
        try:
            returncode = _wait_environment_command(process, command, timeout, cancel)
        finally:
            if process.poll() is None:
                _stop_environment_command(process)
        if cancel is not None and cancel.is_set():
            raise InterruptedError
        if returncode:
            size = diagnostics.tell()
            diagnostics.seek(max(0, size - 6000))
            detail = diagnostics.read().decode("utf-8", errors="replace").strip()
            raise EnvironmentCommandError(returncode, command, stderr=detail)


def windows_cuda_device() -> bool:
    if os.name != "nt":
        return False
    import ctypes
    try:
        driver = ctypes.WinDLL("nvcuda.dll")
        count = ctypes.c_int()
        return driver.cuInit(0) == 0 and driver.cuDeviceGetCount(ctypes.byref(count)) == 0 and count.value > 0
    except (OSError, AttributeError):
        return False


def inference_install_options():
    if os.name != "nt":
        return [], None
    if windows_cuda_device():
        capability = cuda_compute_capability()
        if capability is None or capability[0] * 10 + capability[1] >= CUDA_MINIMUM_CAPABILITY:
            return ["--extra", "cu128"], "cuda-fp32-v1"
    return [], "cpu-fp32-v1"

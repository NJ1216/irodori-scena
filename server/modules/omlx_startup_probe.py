from __future__ import annotations

import socket
from server import subprocess_boundary as subprocess
import time
import urllib.request
from pathlib import Path

from server.modules.omlx_runtime_verification import runtime_import_probe

def verify(staging: Path, *, probe: str | None = None) -> None:
    python = staging / "bin/python"
    subprocess.run(
        [str(python), "-c", probe or runtime_import_probe()], check=True, timeout=90
    )
    subprocess.run([str(python), str(staging / "scena-launcher.py"), "--help"], check=True, stdout=subprocess.DEVNULL, timeout=90)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    model_dir = staging / ".verification-models"
    model_dir.mkdir()
    process = subprocess.Popen(
        [
            str(python),
            str(staging / "scena-launcher.py"),
            "serve",
            "--model-dir",
            str(model_dir),
            "--base-path",
            str(staging / ".verification-state"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--max-concurrent-requests",
            "1",
            "--log-level",
            "warning",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("oMLXサーバーのhealth確認に失敗しました。")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()



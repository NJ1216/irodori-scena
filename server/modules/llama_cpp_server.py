from __future__ import annotations

import os
from server import subprocess_boundary as subprocess
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps

MAX_LOG_BYTES = 2 * 1024 * 1024


def _open_log(path: Path) -> Any:
    try:
        if path.stat().st_size >= MAX_LOG_BYTES:
            previous = path.with_suffix(f"{path.suffix}.1")
            previous.unlink(missing_ok=True)
            path.replace(previous)
    except OSError:
        pass
    return path.open("a", encoding="utf-8")


def model_files(model_id: str) -> list[Path]:
    card = next((item for item in deps.read_llm_registry()["cards"] if item.get("modelId") == model_id), None)
    metadata = (card or {}).get("localMetadata") or {}
    files = metadata.get("files") or ([metadata["path"]] if metadata.get("path") else [])
    paths = [Path(value) for value in files]
    if not paths or any(not path.is_file() for path in paths):
        raise HTTPException(409, "登録済みのGGUFモデルが見つかりません。")
    return paths


def command(model_id: str, port: int, api_key: str, backend: str, context_size: int) -> tuple[list[str], Any]:
    runtime = deps.llama_cpp_runtime_status(backend)
    if not runtime["ready"]:
        raise HTTPException(409, "llama.cpp実行基盤の準備が必要です。")
    files = model_files(model_id)
    log_root = deps.LOCAL_LLM_ROOT / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    log = _open_log(log_root / "llama.cpp.log")
    args = [str(Path(runtime["path"]) / "llama-server.exe"), "--host", "127.0.0.1", "--port", str(port),
            "--api-key", api_key, "--no-webui", "--parallel", "1", "--ctx-size", str(context_size),
            "--model", str(files[0])]
    if backend == "cuda":
        args.extend(["--fit", "on", "--fit-target", "2048", "--fit-ctx", "8192"])
    else:
        args.extend(["--n-gpu-layers", "0"])
    return args, log


def spawn(model_id: str, port: int, api_key: str, backend: str, context_size: int) -> subprocess.Popen[str]:
    args, log = command(model_id, port, api_key, backend, context_size)
    try:
        return subprocess.Popen(args, env={**os.environ}, stdout=log, stderr=subprocess.STDOUT, text=True)
    except OSError as error:
        log.close()
        message = "CUDA版llama.cppを起動できませんでした。CPU版へ切り替える場合は明示的に選択してください。" if backend == "cuda" else "llama.cppを起動できませんでした。"
        raise HTTPException(503, message) from error


deps.register(__name__, ["model_files"])

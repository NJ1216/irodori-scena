from __future__ import annotations

from server.platform_support import require_builtin_llm

import atexit
import os
import platform
import json
import secrets
import socket
from server import subprocess_boundary as subprocess
import sys
import threading
import time
import urllib.request
import urllib.parse
from copy import copy
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps
from server.modules.llm_runtime_binding import serialized, require_load_available

RUNTIME_LOCK = threading.RLock()
RUNTIME_PROCESS: subprocess.Popen[str] | None = None
RUNTIME_PORT = 0
LOADED_MODEL: str | None = None
RUNTIME_ERROR: str | None = None
RUNTIME_API_KEY = ""
RUNTIME_MEMORY_GUARD = "safe"
RUNTIME_ID: str | None = None
RUNTIME_BACKEND = "metal"
RUNTIME_CONTEXT_SIZE: int | None = None


def local_llm_capabilities(memory_gib: int | None = None, system: str | None = None) -> dict[str, Any]:
    del memory_gib
    current_os = system or platform.system()
    if current_os == "Darwin":
        engine, backend = "omlx", "metal"
    elif current_os == "Windows":
        engine, backend = "llama.cpp", deps.selected_backend()
    else:
        engine, backend = "unsupported", "unsupported"
    return {
        "os": current_os.lower(),
        "engine": engine,
        "backend": backend,
        "memoryOwner": deps.memory_ownership(),
        "sequentialResidency": True,
    }


def _runtime_endpoint() -> str:
    configured = os.getenv("SCENA_LOCAL_LLM_ENDPOINT", "").rstrip("/")
    if configured:
        return configured
    if not RUNTIME_PORT:
        raise HTTPException(status_code=503, detail="SCENA内蔵LLMランタイムは起動していません。")
    return f"http://127.0.0.1:{RUNTIME_PORT}/v1"


def _select_runtime_port() -> int:
    configured = os.getenv("SCENA_LOCAL_LLM_PORT", "").strip()
    if configured:
        port = int(configured)
        if not 1 <= port <= 65535:
            raise ValueError("SCENA_LOCAL_LLM_PORTは1〜65535で指定してください。")
        return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def _hot_cache_size(memory_guard: str) -> str:
    """Keep prefix reuse in RAM without creating persistent KV cache files."""
    return {"safe": "2GB", "balanced": "4GB", "aggressive": "8GB"}.get(memory_guard, "2GB")


def local_llm_runtime_endpoint() -> str:
    return _runtime_endpoint()


def local_llm_runtime_api_key() -> str:
    if os.getenv("SCENA_LOCAL_LLM_ENDPOINT"):
        return os.getenv("SCENA_LOCAL_LLM_API_KEY", "")
    return RUNTIME_API_KEY


def local_llm_runtime_pid() -> int | None:
    process = RUNTIME_PROCESS
    return process.pid if process is not None and process.poll() is None else None


def _runtime_request(url: str, *, method: str = "GET") -> urllib.request.Request:
    headers = {}
    if api_key := local_llm_runtime_api_key():
        headers["Authorization"] = f"Bearer {api_key}"
    return urllib.request.Request(url, headers=headers, method=method)


def _runtime_health(endpoint: str) -> bool:
    try:
        with urllib.request.urlopen(_runtime_request(f"{endpoint}/models"), timeout=1) as response:
            return response.status == 200
    except OSError:
        return False


def _llama_runtime_context(endpoint: str) -> int | None:
    try:
        root = endpoint.removesuffix("/v1")
        with urllib.request.urlopen(_runtime_request(f"{root}/props"), timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        settings = payload.get("default_generation_settings") or {}
        value = settings.get("n_ctx", payload.get("n_ctx"))
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def _llama_log_size() -> int:
    try:
        return (deps.LOCAL_LLM_ROOT / "logs" / "llama.cpp.log").stat().st_size
    except OSError:
        return 0


def _llama_start_failure_category(offset: int) -> str:
    try:
        path = deps.LOCAL_LLM_ROOT / "logs" / "llama.cpp.log"
        with path.open("rb") as source:
            source.seek(max(offset, path.stat().st_size - 64 * 1024))
            message = source.read().decode("utf-8", errors="replace").casefold()
    except OSError:
        return "unknown"
    context_needles = ("failed to allocate context", "kv cache", "context size", "failed to create context")
    memory_needles = ("out of memory", "not enough memory", "cuda_error_out_of_memory", "std::bad_alloc")
    if any(value in message for value in context_needles):
        return "context_memory"
    if "failed to load model" in message or "invalid model" in message or "unsupported" in message or "tensor" in message and "not found" in message:
        return "model"
    if any(value in message for value in memory_needles):
        return "memory"
    return "unknown"


def _runtime_command(runtime_id: str | None = None) -> list[str]:
    if runtime_id:
        from server.modules.llm_runtime_binding import runtime_item

        item = runtime_item(runtime_id)
        if not item:
            raise HTTPException(409, "モデルに紐づく実行基盤の準備が必要です。")
        root = Path(item["path"])
        launcher = root / "scena-launcher.py"
        if not launcher.is_file():
            launcher = Path(os.getenv("SCENA_OMLX_LAUNCHER", str(deps.PROJECT_ROOT / "tools/omlx-sidecar.py")))
        return [str(root / "bin/python"), str(launcher)]
    executable = os.getenv("SCENA_OMLX_EXECUTABLE", "")
    launcher = Path(os.getenv("SCENA_OMLX_LAUNCHER", str(deps.PROJECT_ROOT / "tools" / "omlx-sidecar.py")))
    if executable:
        return [executable]
    if deps.omlx_environment_status()["ready"]:
        return [str(deps.omlx_environment_python()), str(launcher)]
    if getattr(sys, "frozen", False):
        raise HTTPException(status_code=503, detail="内蔵LLMに必要なライブラリを先に取得してください。")
    return [sys.executable, str(launcher)]


@serialized
def start_local_llm(memory_guard: str = "safe", *, runtime_id: str | None = None) -> dict[str, Any]:
    global RUNTIME_PROCESS, RUNTIME_PORT, RUNTIME_ERROR, RUNTIME_API_KEY, RUNTIME_MEMORY_GUARD, RUNTIME_ID
    require_builtin_llm()
    endpoint = os.getenv("SCENA_LOCAL_LLM_ENDPOINT", "").rstrip("/")
    if endpoint:
        if not _runtime_health(endpoint):
            raise HTTPException(status_code=503, detail="設定されたSCENA内蔵LLMへ接続できません。")
        return local_llm_status()
    if RUNTIME_PROCESS is not None and RUNTIME_PROCESS.poll() is None:
        if memory_guard == RUNTIME_MEMORY_GUARD and runtime_id == RUNTIME_ID:
            return local_llm_status()
        stop_local_llm()
    if platform.system() == "Windows":
        raise HTTPException(status_code=409, detail="WindowsではロードするGGUFモデルを選択してください。")
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise HTTPException(status_code=503, detail="SCENA内蔵LLMはApple Silicon Macでのみ利用できます。")
    command = _runtime_command(runtime_id) if runtime_id else _runtime_command()
    RUNTIME_ID = runtime_id
    RUNTIME_PORT = _select_runtime_port()
    RUNTIME_API_KEY = secrets.token_urlsafe(32)
    RUNTIME_MEMORY_GUARD = memory_guard
    root = deps.LOCAL_LLM_ROOT
    for name in ("models", "cache", "logs"):
        (root / name).mkdir(parents=True, exist_ok=True)
    discovery = deps.rebuild_local_llm_discovery()
    log = (root / "logs" / "omlx.log").open("a", encoding="utf-8")
    try:
        RUNTIME_PROCESS = subprocess.Popen(
            [
                *command,
                "serve",
                "--model-dir",
                f"{root / 'models'},{discovery}",
                "--base-path",
                str(root / "runtime"),
                "--host",
                "127.0.0.1",
                "--port",
                str(RUNTIME_PORT),
                "--max-concurrent-requests",
                "1",
                "--memory-guard",
                memory_guard,
                "--paged-ssd-cache-dir",
                str(root / "cache"),
                "--hot-cache-max-size",
                _hot_cache_size(memory_guard),
                "--log-level",
                "info",
            ],
            env={
                **os.environ,
                "HF_HOME": str(root / "cache"),
                "OMLX_API_KEY": RUNTIME_API_KEY,
                "OMLX_HOT_CACHE_ONLY": "1",
                "OMLX_GDN_SNAPSHOT_STORAGE": "embedded",
            },
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except OSError as error:
        RUNTIME_ERROR = str(error)
        raise HTTPException(status_code=503, detail="oMLXランタイムを起動できませんでした。") from error
    finally:
        log.close()  # the child keeps its own inherited copy
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and RUNTIME_PROCESS.poll() is None:
        if _runtime_health(_runtime_endpoint()):
            RUNTIME_ERROR = None
            return local_llm_status()
        time.sleep(0.1)
    exited = RUNTIME_PROCESS.poll() is not None
    stop_local_llm()
    if exited:
        raise HTTPException(status_code=503, detail="oMLXランタイムが起動直後に終了しました。ログを確認してください。")
    raise HTTPException(status_code=503, detail="oMLXランタイムの起動確認がタイムアウトしました。")


def _apply_model_settings(model_id: str, settings: dict[str, Any]) -> None:
    endpoint = _runtime_endpoint().removesuffix("/v1")
    encoded = urllib.parse.quote(model_id, safe="")
    mtp_draft_model = None
    if settings.get("mtp"):
        card = next((item for item in deps.read_llm_registry()["cards"] if item.get("modelId") == model_id), None)
        mtp_draft_model = str(deps.resolve_mtp_draft((card or {}).get("localMetadata")))
    payload = json.dumps(
        {
            "max_context_window": settings.get("contextLimit"),
            "ttl_seconds": settings.get("ttlSeconds"),
            "enable_thinking": bool(settings.get("thinking")),
            "trust_remote_code": bool(settings.get("trustRemoteCode")),
            "mtp_enabled": False,
            "vlm_mtp_enabled": bool(settings.get("mtp")),
            "vlm_mtp_draft_model": mtp_draft_model,
        }
    ).encode()
    request = _runtime_request(f"{endpoint}/api/scena/models/{encoded}/settings")
    request.data, request.method = payload, "PUT"
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=10):
        pass


def _load_windows_llm(model_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    global LOADED_MODEL, RUNTIME_PROCESS, RUNTIME_PORT, RUNTIME_API_KEY, RUNTIME_BACKEND, RUNTIME_ERROR, RUNTIME_ID, RUNTIME_CONTEXT_SIZE
    backend = str(settings.get("backend") or deps.selected_backend())
    deps.acquire_llm_memory(f"モデル {model_id} をロード")
    runtime = deps.llama_cpp_runtime_status(backend)
    if not runtime["ready"]:
        raise HTTPException(409, "llama.cpp実行基盤の準備が必要です。")
    card = next((item for item in deps.read_llm_registry()["cards"] if item.get("modelId") == model_id), None)
    metadata = (card or {}).get("localMetadata") or {}
    available = deps.available_memory_bytes(backend)
    if RUNTIME_PROCESS is not None and RUNTIME_PROCESS.poll() is None and LOADED_MODEL == model_id and RUNTIME_BACKEND == backend and isinstance(metadata.get("diskBytes"), int) and isinstance(available, int):
        available += metadata["diskBytes"]
    manual = settings.get("contextLimit")
    context_size = deps.select_context_size(metadata, backend, manual if isinstance(manual, int) else None, available_bytes=available)
    if RUNTIME_PROCESS is not None and RUNTIME_PROCESS.poll() is None:
        if LOADED_MODEL == model_id and RUNTIME_BACKEND == backend and RUNTIME_CONTEXT_SIZE == context_size:
            return local_llm_status()
        stop_local_llm()
    for candidate in deps.fallback_contexts(context_size):
        log_offset = _llama_log_size()
        RUNTIME_PORT, RUNTIME_API_KEY = _select_runtime_port(), secrets.token_urlsafe(32)
        RUNTIME_BACKEND, RUNTIME_ID, RUNTIME_CONTEXT_SIZE = (
            backend,
            f"llama.cpp-{runtime['version']}-{backend}",
            candidate,
        )
        RUNTIME_PROCESS = __import__("server.modules.llama_cpp_server", fromlist=["spawn"]).spawn(model_id, RUNTIME_PORT, RUNTIME_API_KEY, backend, candidate)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and RUNTIME_PROCESS.poll() is None:
            if _runtime_health(_runtime_endpoint()):
                actual_context = _llama_runtime_context(_runtime_endpoint())
                if actual_context is None:
                    stop_local_llm()
                    raise HTTPException(503, "llama.cppの実際のContext割当を確認できませんでした。")
                RUNTIME_CONTEXT_SIZE = actual_context
                LOADED_MODEL, RUNTIME_ERROR = model_id, None
                return local_llm_status()
            time.sleep(0.1)
        exited = RUNTIME_PROCESS.poll() is not None
        category = _llama_start_failure_category(log_offset)
        stop_local_llm()
        if category not in {"context_memory", "memory"} or candidate == 8192:
            if category in {"context_memory", "memory"}:
                raise HTTPException(503, f"{backend.upper()}メモリ不足のためContext 8,192を確保できません。")
            raise HTTPException(503, "llama.cppが起動直後に終了しました。" if exited else "llama.cppの起動確認がタイムアウトしました。")
    raise HTTPException(503, "llama.cppを起動できませんでした。")


@serialized
def load_local_llm(model_id: str, *, settings: dict[str, Any] | None = None, runtime_id: str | None = None) -> dict[str, Any]:
    global LOADED_MODEL
    require_load_available(model_id)
    settings = settings or {}
    if platform.system() == "Windows" and not os.getenv("SCENA_LOCAL_LLM_ENDPOINT"):
        return _load_windows_llm(model_id, settings)
    external = next((item for item in deps.external_local_llm_models() if item["id"] == model_id), None)
    managed_path = deps.LOCAL_LLM_ROOT / "models" / model_id
    if external is None:
        installed = (managed_path / "config.json").is_file() and any(managed_path.glob("*.safetensors"))
    else:
        if not external["pathAvailable"]:
            raise HTTPException(status_code=409, detail="外部モデルが利用できません。ボリュームを接続して再走査してください。")
        installed = True
    if not installed and not os.getenv("SCENA_LOCAL_LLM_ENDPOINT"):
        raise HTTPException(status_code=409, detail="登録済みのMLXモデルが見つかりません。")
    if not os.getenv("SCENA_LOCAL_LLM_ENDPOINT"):
        from server.modules.llm_runtime_binding import model_runtime

        runtime_id = runtime_id or model_runtime(model_id)
        start_local_llm(str(settings.get("memoryGuard") or "safe"), runtime_id=runtime_id)
    else:
        start_local_llm(str(settings.get("memoryGuard") or "safe"))
    if not os.getenv("SCENA_LOCAL_LLM_ENDPOINT"):
        _apply_model_settings(model_id, settings)
    deps.acquire_llm_memory(f"モデル {model_id} をロード")
    LOADED_MODEL = model_id
    return local_llm_status()


@serialized
def unload_local_llm() -> dict[str, Any]:
    global LOADED_MODEL
    if not os.getenv("SCENA_LOCAL_LLM_ENDPOINT"):
        # oMLX owns the Metal allocation. Stopping its SCENA-owned process is
        # the only portable guarantee that unified memory has been reclaimed.
        return stop_local_llm()
    generation = deps.memory_generation("llm")
    with RUNTIME_LOCK:
        LOADED_MODEL = None
    deps.release_memory("llm", generation=generation)
    return local_llm_status()


@serialized
def stop_local_llm() -> dict[str, Any]:
    global RUNTIME_PROCESS, RUNTIME_PORT, LOADED_MODEL, RUNTIME_API_KEY, RUNTIME_CONTEXT_SIZE
    generation = deps.memory_generation("llm")
    with RUNTIME_LOCK:
        process = RUNTIME_PROCESS
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    with RUNTIME_LOCK:
        if RUNTIME_PROCESS is not process:
            return local_llm_status()
        RUNTIME_PROCESS = None
        RUNTIME_PORT, LOADED_MODEL, RUNTIME_API_KEY, RUNTIME_CONTEXT_SIZE = 0, None, "", None
    deps.release_memory("llm", generation=generation)
    return local_llm_status()


def local_llm_status() -> dict[str, Any]:
    external = bool(os.getenv("SCENA_LOCAL_LLM_ENDPOINT"))
    running = external or (RUNTIME_PROCESS is not None and RUNTIME_PROCESS.poll() is None)
    windows = platform.system() == "Windows"
    environment = deps.llama_cpp_runtime_status(RUNTIME_BACKEND if windows else None) if windows else deps.omlx_environment_status()
    engine = "llama.cpp" if windows else "omlx"
    version = environment.get("version") if windows else environment.get("omlxVersion")
    return {
        "state": "ready" if running else "stopped",
        "running": running,
        "model": LOADED_MODEL,
        "error": RUNTIME_ERROR,
        "runtimeId": RUNTIME_ID,
        "runtime": environment,
        "engine": engine,
        "version": version,
        "backend": RUNTIME_BACKEND if windows else "metal",
        "contextSize": RUNTIME_CONTEXT_SIZE,
        "capabilities": local_llm_capabilities(),
    }


def local_llm_metal_memory() -> int | None:
    """Compatibility entry point; aggregate metrics live in local_llm_metrics."""
    return deps.local_llm_metal_memory()


def _updated_request(request: Any, update: dict[str, Any]) -> Any:
    model_copy = getattr(request, "model_copy", None)
    if callable(model_copy):
        return model_copy(update=update)
    updated = copy(request)
    for key, value in update.items():
        setattr(updated, key, value)
    return updated


def resolve_logical_llm_request(request: Any) -> Any:
    """Fill an omitted connection from the selected card without changing its provider."""
    if not getattr(request, "base_url", "") or not getattr(request, "model", ""):
        selected = deps.operation_llm_selection() or deps.resolve_default_llm()
        return _updated_request(
            request,
            {
                "base_url": selected["baseUrl"],
                "model": selected["model"],
                "api_key": selected["apiKey"],
                "provider": selected["provider"],
            },
        )
    return request


def resolve_local_llm_request(request: Any) -> Any:
    request = resolve_logical_llm_request(request)
    if request.provider != "scena-local":
        return request
    require_builtin_llm()
    require_load_available(request.model)
    external = bool(os.getenv("SCENA_LOCAL_LLM_ENDPOINT"))
    managed_runtime_ready = external or RUNTIME_PROCESS is not None and RUNTIME_PROCESS.poll() is None and RUNTIME_PORT > 0 and bool(RUNTIME_API_KEY) and _runtime_health(_runtime_endpoint())
    if not managed_runtime_ready and not external:
        stop_local_llm()
    if LOADED_MODEL != request.model or not managed_runtime_ready:
        settings = deps.resolve_llm_settings(request.provider, request.base_url, request.model)
        load_local_llm(request.model, settings=settings)
    deps.acquire_llm_memory("SCENA内蔵LLM推論")
    return _updated_request(request, {"base_url": _runtime_endpoint(), "api_key": local_llm_runtime_api_key(), "provider": "openai"})


atexit.register(stop_local_llm)
deps.register(
    __name__,
    [
        "load_local_llm",
        "local_llm_capabilities",
        "local_llm_status",
        "resolve_local_llm_request",
        "resolve_logical_llm_request",
        "local_llm_runtime_api_key",
        "local_llm_runtime_endpoint",
        "local_llm_runtime_pid",
        "start_local_llm",
        "stop_local_llm",
        "unload_local_llm",
    ],
)

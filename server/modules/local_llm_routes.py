from __future__ import annotations

from typing import Any

from server.app_deps import HTTPException
from server.registry import deps


@deps.app.get("/api/local-llm/status")
def get_local_llm_status() -> dict[str, Any]:
    return deps.local_llm_status()


@deps.app.get("/api/local-llm/capabilities")
def get_local_llm_capabilities() -> dict[str, Any]:
    return deps.local_llm_capabilities()


@deps.app.get("/api/local-llm/llama-cpp/runtime")
def get_llama_cpp_runtime(backend: str | None = None) -> dict[str, Any]:
    return deps.llama_cpp_runtime_status(backend)


@deps.app.post("/api/local-llm/llama-cpp/runtime/install")
def install_llama_cpp_runtime(options: dict[str, Any] | None = None) -> dict[str, Any]:
    return deps.install_llama_cpp_runtime((options or {}).get("backend"))


@deps.app.put("/api/local-llm/llama-cpp/runtime/selection")
def select_llama_cpp_runtime(options: dict[str, Any]) -> dict[str, Any]:
    return deps.select_llama_cpp_backend(options.get("backend"))


@deps.app.post("/api/local-llm/llama-cpp/runtime/cancel")
def cancel_llama_cpp_runtime() -> dict[str, Any]:
    return deps.cancel_llama_cpp_runtime_install()


@deps.app.delete("/api/local-llm/llama-cpp/runtime/{backend}")
def delete_llama_cpp_runtime(backend: str) -> dict[str, Any]:
    return deps.delete_llama_cpp_runtime(backend)


@deps.app.post("/api/local-llm/start")
def start_managed_local_llm() -> dict[str, Any]:
    selected = deps.resolve_default_llm()
    if selected["provider"] != "scena-local":
        raise HTTPException(409, "ローカルモデルを選択してください。")
    return deps.load_local_llm(selected["model"], settings=selected["settings"])


@deps.app.post("/api/local-llm/models/{model_id}/load")
def load_managed_local_llm(model_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return deps.load_local_llm(model_id, settings=options or {})
    except KeyError as error:
        raise HTTPException(status_code=404, detail="モデルカタログに存在しません。") from error


@deps.app.post("/api/local-llm/unload")
def unload_managed_local_llm() -> dict[str, Any]:
    from server.modules.llm_runtime_binding import require_idle
    require_idle()
    return deps.unload_local_llm()


@deps.app.post("/api/local-llm/stop")
def stop_managed_local_llm() -> dict[str, Any]:
    from server.modules.llm_runtime_binding import require_idle
    require_idle()
    return deps.stop_local_llm()

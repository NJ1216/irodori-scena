from __future__ import annotations

from typing import Any

from server.registry import deps


@deps.app.get("/api/local-llm/runtimes")
def get_runtimes() -> dict[str, Any]:
    from server.modules.llm_runtime_binding import deletion_reason, runtime_references
    status = deps.omlx_runtimes_status()
    for item in status["installedRuntimes"]:
        for key in ("installSpec", "launcher", "requirements", "resolvedRequirements", "importProbe"):
            item.pop(key, None)
        item["usedByModels"] = runtime_references(item["id"])
        item["deletionBlockedReason"] = deletion_reason(item["id"])
    return status


@deps.app.get("/api/local-llm/runtime-releases")
def get_releases() -> dict[str, Any]:
    return {"repository": "jundot/omlx", "releases": deps.list_omlx_releases()}


@deps.app.post("/api/local-llm/runtimes/install")
def start_runtime_install(options: dict[str, Any]) -> dict[str, Any]:
    value = options.get("tag")
    tag = value.strip() if isinstance(value, str) else None
    return deps.install_omlx_runtime(tag or None)


@deps.app.post("/api/local-llm/runtimes/{runtime_id}/activate")
def activate_runtime(runtime_id: str) -> dict[str, Any]:
    return deps.switch_omlx_runtime(runtime_id)


@deps.app.delete("/api/local-llm/runtimes/{runtime_id}")
def remove_runtime(runtime_id: str) -> dict[str, Any]:
    return deps.delete_omlx_runtime(runtime_id)


@deps.app.get("/api/local-llm/runtime")
def get_environment() -> dict[str, Any]:
    return deps.omlx_environment_status()


@deps.app.post("/api/local-llm/runtime/install")
def start_environment_install() -> dict[str, Any]:
    return deps.install_omlx_environment()


@deps.app.post("/api/local-llm/runtime/cancel")
def cancel_environment() -> dict[str, Any]:
    deps.cancel_omlx_environment_install()
    return deps.omlx_environment_status()


@deps.app.post("/api/llm/cards/{card_id}/runtime")
def prepare_model_runtime(card_id: str, options: dict[str, Any]) -> dict[str, Any]:
    from server.modules.model_runtime_jobs import start_model_runtime
    from server.app_deps import HTTPException
    for key in ("runtimeId", "tag"):
        if options.get(key) is not None and not isinstance(options[key], str):
            raise HTTPException(422, "実行基盤または公開版を文字列で指定してください。")
    return start_model_runtime(card_id, options.get("runtimeId"), options.get("tag"))


@deps.app.post("/api/llm/cards/{card_id}/runtime/cancel")
def cancel_model_runtime(card_id: str) -> dict[str, Any]:
    from server.modules.model_runtime_jobs import cancel_model_runtime as cancel
    return cancel(card_id)

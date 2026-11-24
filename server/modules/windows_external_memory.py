"""Windows-only accelerator handoff for externally hosted local LLMs."""

from __future__ import annotations
from functools import wraps
from types import SimpleNamespace
from typing import Any, Callable
from server.app_deps import http, json, sys, urllib
from server.modules.llm_runtime_binding import LOCK
from server.registry import deps

_OWNED_MODELS: dict[tuple[str, str, str], dict[str, str]] = {}


def _is_windows_local(request: Any) -> bool:
    model = str(getattr(request, "model", "")).strip().casefold()
    ollama_cloud = request.provider == "ollama" and (
        model.endswith(":cloud") or model.endswith("-cloud")
    )
    return sys.platform == "win32" and request.provider in {"ollama", "lmstudio"} and not ollama_cloud


def _headers(request: Any) -> dict[str, str]:
    return deps.request_headers(request.api_key)


def _get_json(url: str, request: Any) -> dict[str, Any]:
    call = urllib.request.Request(url, headers=_headers(request), method="GET")
    with urllib.request.urlopen(call, timeout=10) as response:
        value = json.loads(response.read().decode("utf-8"))
    return value if isinstance(value, dict) else {}


def _ollama_loaded(request: Any) -> bool:
    items = _get_json(f"{deps.ollama_api_root(request.base_url)}/api/ps", request).get("models", [])
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("name") or item.get("model") or "").strip() == request.model
        for item in items
    )


def _lmstudio_instances(request: Any) -> list[str]:
    payload = _get_json(f"{deps.lmstudio_api_root(request.base_url)}/models", request)
    items = payload.get("models", payload.get("data", []))
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("key") or item.get("id") or item.get("model") or "").strip()
        if name != request.model:
            continue
        instances = item.get("loaded_instances", item.get("loadedInstances", []))
        for instance in instances if isinstance(instances, list) else []:
            if isinstance(instance, dict):
                identifier = str(instance.get("id") or instance.get("identifier") or name).strip()
                if identifier:
                    result.append(identifier)
    return result


def _loaded(request: Any) -> bool:
    try:
        return _ollama_loaded(request) if request.provider == "ollama" else bool(_lmstudio_instances(request))
    except (OSError, ValueError, http.client.HTTPException):
        return False


def _remember(request: Any) -> None:
    key = (request.provider, request.base_url, request.model)
    _OWNED_MODELS[key] = {
        "provider": request.provider,
        "baseUrl": request.base_url,
        "model": request.model,
        "apiKey": request.api_key,
    }


def windows_accelerator_handoff(function: Callable[..., Any]) -> Callable[..., Any]:
    """Keep a Windows local-LLM call exclusive with the resident TTS worker."""

    @wraps(function)
    def guarded(request: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_windows_local(request):
            return function(request, *args, **kwargs)
        with LOCK:
            was_loaded = _loaded(request)
            deps.acquire_llm_memory(f"{request.provider} LLM推論")
            try:
                return function(request, *args, **kwargs)
            finally:
                if not was_loaded and _loaded(request):
                    _remember(request)

    return guarded


def _owned_request(model: dict[str, str]) -> Any:
    return SimpleNamespace(
        provider=model["provider"], base_url=model["baseUrl"], model=model["model"], api_key=model["apiKey"]
    )


def _post(url: str, request: Any, payload: dict[str, Any]) -> None:
    call = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=_headers(request), method="POST"
    )
    with urllib.request.urlopen(call, timeout=15) as response:
        response.read()


def release_windows_external_llm() -> None:
    """Unload only external models that SCENA caused to be loaded on Windows."""
    if sys.platform != "win32" or not _OWNED_MODELS:
        return
    models = list(_OWNED_MODELS.values())
    _OWNED_MODELS.clear()
    for model in models:
        request = _owned_request(model)
        try:
            if request.provider == "ollama":
                _post(
                    f"{deps.ollama_api_root(request.base_url)}/api/generate",
                    request,
                    {"model": request.model, "keep_alive": 0},
                )
            else:
                for identifier in _lmstudio_instances(request):
                    _post(
                        f"{deps.lmstudio_api_root(request.base_url)}/models/unload",
                        request,
                        {"instance_id": identifier},
                    )
        except (OSError, ValueError, http.client.HTTPException):
            pass


deps.register(__name__, ["release_windows_external_llm"])

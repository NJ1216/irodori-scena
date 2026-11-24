from __future__ import annotations

from server.app_deps import Any, json, subprocess, sys, urllib
from server.registry import deps


def local_memory_gib() -> float | None:
    """Return macOS unified memory; other platforms use the safe fallback."""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=2, check=True
            )
            return int(result.stdout.strip()) / 1024**3
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
    return None


def local_hardware_name() -> str | None:
    """Return the macOS CPU brand when it is available for author-facing diagnostics."""
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2, check=True
            )
            return result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            return None
    return None


def ollama_api_root(base_url: str) -> str:
    base = base_url.rstrip("/")
    return base[:-3] if base.endswith("/v1") else base


def _ollama_context_length(value: Any) -> int | None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).endswith("context_length") and isinstance(item, int) and item >= 4096:
                return item
        for item in value.values():
            found = _ollama_context_length(item)
            if found:
                return found
    return None


def _ollama_json(
    url: str, *, method: str = "GET", body: dict[str, Any] | None = None, headers: dict[str, str]
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    call = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(call, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def ollama_runtime_details(request: deps.DraftRequest) -> tuple[int | None, int | None, str | None]:
    """Return model maximum and currently loaded context from native Ollama APIs."""
    try:
        root = ollama_api_root(request.base_url)
        headers = deps.request_headers(request.api_key)
        show = _ollama_json(f"{root}/api/show", method="POST", body={"model": request.model}, headers=headers)
        model_limit = _ollama_context_length(show.get("model_info")) or _ollama_context_length(show)
        running = _ollama_json(f"{root}/api/ps", headers=headers)
        for item in running.get("models", []):
            if isinstance(item, dict) and str(item.get("name") or item.get("model") or "") == request.model:
                active = _ollama_context_length(item)
                direct = item.get("context_length")
                return model_limit, active or (direct if isinstance(direct, int) and direct >= 4096 else None), None
        return model_limit, None, None
    except (OSError, ValueError, urllib.error.HTTPError) as error:
        return None, None, f"Ollama詳細取得失敗: {error}"

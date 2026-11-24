from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from server.modules import local_llm_runtime as runtime
from server.registry import deps


def local_llm_metal_memory() -> int | None:
    if not runtime.local_llm_status()["running"]:
        return 0
    try:
        root = runtime._runtime_endpoint().removesuffix("/v1")
        with urllib.request.urlopen(runtime._runtime_request(f"{root}/api/scena/metrics"), timeout=1) as response:
            metrics = json.loads(response.read().decode("utf-8"))
            value = metrics.get("modelMemoryBytes", metrics.get("activeMemoryBytes"))
        return max(0, int(value)) if not isinstance(value, bool) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def local_llm_engine_status(model_id: str) -> dict[str, Any]:
    endpoint = runtime._runtime_endpoint().removesuffix("/v1")
    encoded = urllib.parse.quote(model_id, safe="")
    with urllib.request.urlopen(runtime._runtime_request(f"{endpoint}/api/scena/models/{encoded}/engine"), timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def local_llm_cache_metrics(model_id: str) -> dict[str, Any] | None:
    if not runtime.local_llm_status()["running"]:
        return None
    endpoint = runtime._runtime_endpoint().removesuffix("/v1")
    encoded = urllib.parse.quote(model_id, safe="")
    try:
        with urllib.request.urlopen(runtime._runtime_request(f"{endpoint}/api/scena/models/{encoded}/cache-metrics"), timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def reset_local_llm_peak_memory() -> dict[str, Any] | None:
    if not runtime.local_llm_status()["running"]:
        return None
    root = runtime._runtime_endpoint().removesuffix("/v1")
    try:
        with urllib.request.urlopen(runtime._runtime_request(f"{root}/api/scena/benchmark/reset-peak-memory", method="POST"), timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


deps.register(__name__, ["local_llm_cache_metrics", "local_llm_engine_status", "local_llm_metal_memory", "reset_local_llm_peak_memory"])

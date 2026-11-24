from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

from server.app_deps import HTTPException
from server.registry import deps
from server.modules import llm_registry
from server.modules.llm_runtime_binding import serialized
from server.modules.llm_catalog import effective_capabilities

T = TypeVar("T")


def resolve_llm_capabilities(provider: str, base_url: str, model: str) -> dict[str, Any]:
    registry = deps.read_llm_registry()
    endpoint = next((item for item in registry["endpoints"] if item.get("provider") == provider
                     and str(item.get("baseUrl", "")).rstrip("/") == base_url.rstrip("/")), None)
    card = next((item for item in registry["cards"] if endpoint and item.get("endpointId") == endpoint.get("id")
                 and item.get("modelId") == model), None)
    return effective_capabilities(provider, base_url, model, (card or {}).get("capabilities"))


@serialized
def set_llm_probe(card_id: str, probe: dict[str, Any], capabilities: dict[str, Any] | None = None) -> None:
    registry = deps.read_llm_registry()
    card = next((item for item in registry["cards"] if item.get("id") == card_id), None)
    if card is not None:
        card["lastProbe"] = probe
        if capabilities is not None:
            card["capabilities"] = capabilities
        deps.write_llm_registry(registry)


@serialized
def set_structured_output_state(provider: str, base_url: str, model: str, *, stream: bool,
                                state: str, reason_code: str | None) -> None:
    """Atomically update one mode without losing concurrent card metadata."""
    registry = deps.read_llm_registry()
    endpoint = next((item for item in registry["endpoints"] if item.get("provider") == provider
                     and str(item.get("baseUrl", "")).rstrip("/") == base_url.rstrip("/")), None)
    card = next((item for item in registry["cards"] if endpoint and item.get("endpointId") == endpoint.get("id")
                 and item.get("modelId") == model), None)
    if card is None:
        return
    capabilities = dict(card.get("capabilities") or {})
    structured = dict(capabilities.get("structuredOutput") or {})
    structured["streaming" if stream else "nonStreaming"] = {"state": state, "reasonCode": reason_code}
    structured["checkedAt"] = int(time.time() * 1000)
    capabilities["structuredOutput"] = structured
    card["capabilities"] = capabilities
    deps.write_llm_registry(registry)


@serialized
def record_llm_usage(card_id: str | None, feature: str, success: bool, error: str | None = None) -> None:
    registry = deps.read_llm_registry()
    card = next((item for item in registry["cards"] if item.get("id") == card_id), None)
    if card is None:
        return
    summary = " ".join((error or "").split())[:300] or None
    card["usageHistory"] = ([{"feature": feature[:80], "success": success,
                              "usedAt": int(time.time() * 1000), "error": summary}] + card.get("usageHistory", []))[:20]
    deps.write_llm_registry(registry)


def track_default_llm_usage(feature: str, operation: Callable[[], T]) -> T:
    card_id = deps.read_llm_registry().get("defaultCardId")
    with deps.llm_operation(feature):
        try:
            result = operation()
        except Exception as error:
            if card_id:
                summary = f"{error.status_code} {type(error).__name__}" if isinstance(error, HTTPException) else type(error).__name__
                record_llm_usage(str(card_id), feature, False, summary)
            raise
        if card_id:
            record_llm_usage(str(card_id), feature, True)
        return result


deps.register(__name__, ["record_llm_usage", "resolve_llm_capabilities", "set_llm_probe",
                         "set_structured_output_state", "track_default_llm_usage"])
# Preserve direct-module compatibility while metadata remains the owner.
llm_registry.record_llm_usage = record_llm_usage
llm_registry.track_default_llm_usage = track_default_llm_usage

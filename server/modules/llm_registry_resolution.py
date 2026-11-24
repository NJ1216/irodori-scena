from __future__ import annotations

from typing import Any
from server.app_deps import HTTPException
from server.platform_support import require_builtin_llm


def resolve_default_llm_impl(runtime) -> dict[str, Any]:
    registry = runtime.read()
    return resolve_llm_card_impl(str(registry["defaultCardId"] or ""), runtime)


def resolve_llm_card_impl(card_id: str, runtime) -> dict[str, Any]:
    registry = runtime.read()
    card = next((item for item in registry["cards"] if item.get("id") == card_id), None)
    if card is None:
        raise HTTPException(status_code=422, detail="既定のLLMモデルを接続ページで選択してください。")
    endpoint = next(item for item in registry["endpoints"] if item.get("id") == card["endpointId"])
    if endpoint["provider"] == "scena-local":
        require_builtin_llm()
    credential = runtime.read_credential(str(endpoint["id"]))
    return {
        "provider": endpoint["provider"],
        "baseUrl": endpoint["baseUrl"],
        "model": card["modelId"],
        "apiKey": credential,
        "cardId": card["id"],
        "source": card.get("source"),
        "runtimeId": card.get("runtimeId"),
        "localMetadata": card.get("localMetadata"),
        "settings": card.get("settings") or {},
        "capabilities": card.get("capabilities"),
    }


def resolve_llm_settings_impl(provider: str, base_url: str, model: str, runtime) -> dict[str, Any]:
    registry = runtime.read()
    endpoint = next(
        (
            item
            for item in registry["endpoints"]
            if item.get("provider") == provider and str(item.get("baseUrl", "")).rstrip("/") == base_url.rstrip("/")
        ),
        None,
    )
    if endpoint is None:
        local_ids = {item.get("id") for item in registry["endpoints"] if item.get("provider") == "scena-local"}
        card = next(
            (
                item
                for item in registry["cards"]
                if item.get("endpointId") in local_ids and item.get("modelId") == model
            ),
            None,
        )
    else:
        card = next(
            (
                item
                for item in registry["cards"]
                if item.get("endpointId") == endpoint.get("id") and item.get("modelId") == model
            ),
            None,
        )
    return dict((card or {}).get("settings") or {})


def set_llm_test_status_impl(card_id: str, status: dict[str, Any], runtime) -> None:
    registry = runtime.read()
    card = next((item for item in registry["cards"] if item.get("id") == card_id), None)
    if card is not None:
        card["testStatus"] = status
        runtime.write(registry)

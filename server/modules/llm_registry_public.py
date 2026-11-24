from __future__ import annotations

from typing import Any
from server.registry import deps
from server.modules.llm_catalog import effective_capabilities


def public_llm_registry_impl(runtime) -> dict[str, Any]:
    registry = runtime.read()
    from server.modules.model_runtime_jobs import model_runtime_status

    changed = runtime.invalidate(registry)
    if changed:
        runtime.write(registry)
    loaded = deps.local_llm_status().get("model")
    cards = [
        {
            **item,
            "localMetadata": {
                **(item.get("localMetadata") or {}),
                "loadState": "loaded" if item.get("modelId") == loaded else "unloaded",
            },
        }
        if item.get("source") in {"managed", "external"}
        else item
        for item in registry["cards"]
    ]
    cards = [
        {
            **item,
            "mtp": {
                **deps.mtp_compatibility(item.get("localMetadata")),
                "enabled": bool((item.get("settings") or {}).get("mtp")),
            },
        }
        for item in cards
    ]
    endpoints = {item["id"]: item for item in registry["endpoints"]}
    cards = [
        {
            **item,
            "capabilities": effective_capabilities(
                endpoints[item["endpointId"]]["provider"],
                endpoints[item["endpointId"]]["baseUrl"],
                item["modelId"],
                item.get("capabilities"),
            ),
        }
        for item in cards
    ]
    for card in cards:
        if card.get("runtimeId"):
            card["runtime"] = model_runtime_status(card)
    return {
        **registry,
        "cards": cards,
        "endpoints": [
            {**item, "hasCredential": runtime.has_credential(str(item["id"]))} for item in registry["endpoints"]
        ],
    }

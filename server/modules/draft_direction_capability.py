from __future__ import annotations

import sys
from typing import Any
from server.registry import deps


def build_direction_capability_profile_impl(request: Any, runtime: Any) -> dict[str, Any]:
    """Resolve the hard AI-direction ceiling for one job."""
    logical = deps.resolve_logical_llm_request(request)
    provider = logical.provider
    memory_gib = runtime.local_memory_gib()
    memory_limit = runtime.target_context_for_memory(memory_gib)
    model_limit: int | None = None
    running_limit: int | None = None
    lookup_error: str | None = None
    card_limit: int | None = None
    if provider == "scena-local":
        selected = deps.resolve_default_llm()
        model_limit = runtime.configured_model_limit({**selected, "settings": {}})
        card_limit = runtime.configured_model_limit({"settings": selected.get("settings"), "localMetadata": {}})
        if sys.platform == "win32":
            deps.load_local_llm(selected["model"], settings=selected.get("settings") or {})
            runtime = deps.local_llm_status()
            running_limit = runtime.get("contextSize")
            if not isinstance(running_limit, int):
                raise RuntimeError("内蔵LLMの実割当Contextを確認できません。送信前に停止しました。")
    elif provider == "ollama":
        model_limit, running_limit, lookup_error = runtime.ollama_runtime_details(logical)
        allocation = runtime.resolve_ollama_context(logical, model_limit, running_limit)
        ceiling = allocation["contextCeiling"]
        if ceiling is None:
            return {
                "provider": provider,
                **allocation,
                "directionChunkSize": 30,
                "directionChunkCapacity": 30,
                "fallbackReason": lookup_error or "Ollama Cloudのためローカル実割当Context確認を省略",
                "detectedMemoryGiB": memory_gib,
            }
        return {
            "provider": provider,
            **allocation,
            "directionChunkSize": runtime.direction_chunk_size_for_context(ceiling),
            "directionChunkCapacity": runtime.direction_chunk_size_for_context(ceiling),
            "fallbackReason": lookup_error or "Ollama実割当Contextを適用",
            "detectedMemoryGiB": memory_gib,
        }
    elif provider == "lmstudio":
        model_limit, running_limit, lookup_error = deps.lmstudio_runtime_details(logical)
    elif provider == "openai":
        settings = deps.resolve_llm_settings(logical.provider, logical.base_url, logical.model)
        card_limit = settings.get("contextLimit")
        if not isinstance(card_limit, int) or isinstance(card_limit, bool):
            discovered = deps.resolve_llm_capabilities(logical.provider, logical.base_url, logical.model).get(
                "inputTokenLimit"
            )
            card_limit = discovered if isinstance(discovered, int) and not isinstance(discovered, bool) else None
        if not isinstance(card_limit, int) or isinstance(card_limit, bool):
            return {
                "provider": provider,
                "effectiveContext": None,
                "contextCeiling": None,
                "directionChunkSize": 30,
                "directionChunkCapacity": 30,
                "fallbackReason": "Context上限が未知のため32Kをsoft targetとして30行から開始",
                "detectedMemoryGiB": memory_gib,
            }
        ceiling = card_limit
        return {
            "provider": provider,
            "cardContextLimit": card_limit,
            "contextCeiling": ceiling,
            "effectiveContext": ceiling,
            "directionChunkSize": runtime.direction_chunk_size_for_context(ceiling),
            "directionChunkCapacity": runtime.direction_chunk_size_for_context(ceiling),
            "fallbackReason": "モデルカードのContext上限を内部適合判定へ適用",
            "detectedMemoryGiB": memory_gib,
        }
    else:
        return {
            "provider": provider,
            "effectiveContext": None,
            "contextCeiling": None,
            "directionChunkSize": 30,
            "directionChunkCapacity": 30,
            "fallbackReason": "一般OpenAI互換接続は30行から開始",
            "detectedMemoryGiB": memory_gib,
        }
    limits = [
        32768,
        *([] if provider == "scena-local" and sys.platform == "win32" else [memory_limit]),
        *[value for value in (model_limit, card_limit, running_limit) if value],
    ]
    ceiling = max(4096, min(limits))
    reasons = [
        reason
        for reason in (
            lookup_error,
            "モデルカード上限を適用" if card_limit and card_limit == ceiling else "",
            "実行中Context上限を適用" if running_limit and running_limit == ceiling else "",
            "搭載メモリの安全上限を適用" if memory_limit == ceiling else "",
            "AI演出上限32Kを適用" if ceiling == 32768 else "",
        )
        if reason
    ]
    runtime_evidence = deps.direction_runtime_evidence(selected, ceiling) if provider == "scena-local" else None
    return {
        "provider": provider,
        "modelContextLimit": model_limit,
        "cardContextLimit": card_limit,
        "runningContext": running_limit,
        "contextCeiling": ceiling,
        "effectiveContext": ceiling,
        "directionChunkSize": min(
            runtime.direction_chunk_size_for_context(ceiling),
            deps.validated_direction_chunk(provider, logical.model, runtime_evidence),
        ),
        "directionChunkCapacity": runtime.direction_chunk_size_for_context(ceiling),
        "fallbackReason": "；".join(reasons),
        "detectedMemoryGiB": memory_gib,
    }

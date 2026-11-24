"""Resolve Ollama allocation without imposing macOS memory heuristics."""
from __future__ import annotations

import json
import math

from server.registry import deps
from server.modules.windows_external_memory import windows_accelerator_handoff


class DraftContextError(RuntimeError):
    code = "draft_context_insufficient"


def is_ollama_cloud_model(model: str) -> bool:
    """Return whether Ollama routes this model to its remote cloud service."""
    normalized = str(model).strip().casefold()
    return normalized.endswith(":cloud") or normalized.endswith("-cloud")


@windows_accelerator_handoff
def load_ollama_allocation(request, *, context: int | None = None, should_cancel=None) -> int:
    """Empty generate is Ollama's documented preload, with no creative output."""
    payload = {"model": request.model, "stream": False, "keep_alive": "300s"}
    if context is not None:
        payload["options"] = {"num_ctx": context}
    connection = None
    try:
        deps._raise_if_draft_cancelled(should_cancel)
        connection, response = deps.openai_http_post(
            f"{deps.ollama_api_root(request.base_url)}/api/generate",
            body=json.dumps(payload).encode(), headers=deps.request_headers(request.api_key),
            should_cancel=should_cancel,
        )
        result = response.read()
        deps._raise_if_draft_cancelled(should_cancel)
        if response.status >= 400:
            raise deps.classify_http_failure(response.status, result.decode("utf-8", errors="replace"))
        _model_limit, active, error = deps.ollama_runtime_details(request)
        if not active:
            raise DraftContextError(f"Ollamaロード後の実割当Contextを確認できません。{error or ''}")
        return active
    finally:
        if connection is not None:
            deps.close_openai_http_post(connection)


def resolve_ollama_context(request, model_limit, running_limit, *, should_cancel=None):
    settings = deps.resolve_llm_settings(request.provider, request.base_url, request.model)
    card = settings.get("contextLimit")
    card = card if type(card) is int and card > 0 else None
    if is_ollama_cloud_model(request.model):
        known = [value for value in (model_limit, card) if type(value) is int and value > 0]
        ceiling = min(known) if known else None
        return {"modelContextLimit": model_limit, "runningContext": None,
                "cardContextLimit": card, "contextCeiling": ceiling, "effectiveContext": ceiling,
                "requestedContext": None, "jobContext": ceiling, "contextApplied": False,
                "remoteCloud": True}
    wanted = min(card, model_limit) if card and model_limit else card
    if running_limit is None or (wanted and wanted > running_limit):
        running_limit = load_ollama_allocation(request, context=wanted, should_cancel=should_cancel)
    ceiling = min(value for value in (model_limit, running_limit, card) if type(value) is int and value > 0)
    return {"modelContextLimit": model_limit, "runningContext": running_limit,
            "cardContextLimit": card, "contextCeiling": ceiling, "effectiveContext": ceiling,
            "requestedContext": wanted or running_limit, "jobContext": ceiling}


def prepare_pinned_call(profile, *, input_tokens, max_tokens, feature):
    ceiling = profile.get("contextCeiling")
    pinned_job = profile.get("jobContext")
    if isinstance(pinned_job, int):
        output = min(max_tokens, pinned_job - input_tokens - deps.DRAFT_CONTEXT_SAFETY_MARGIN)
        if output < min(256, max_tokens):
            raise DraftContextError(
                f"固定必須入力 {input_tokens} + 出力予約 {min(256, max_tokens)} + "
                f"安全余白 {deps.DRAFT_CONTEXT_SAFETY_MARGIN} tokenがContext {pinned_job} tokenへ収まりません。")
        profile["effectiveContext"] = pinned_job
        profile["actualPromptTokenEstimate"] = input_tokens
        profile["lastCall"] = {"feature": feature, "logicalProvider": profile.get("provider"),
            "contextCeiling": ceiling, "selectedContext": pinned_job, "inputTokenEstimate": input_tokens,
            "outputTokenLimit": output, "safetyMargin": deps.DRAFT_CONTEXT_SAFETY_MARGIN,
            "shrinkReasons": ["output_reservation_reduced"] if output < max_tokens else []}
        profile.setdefault("calls", []).append(profile["lastCall"])
        return output


def ollama_draft_profile(request, model_limit, running_limit, *, prompt_estimate, target_characters,
                         adaptive_long_form, should_cancel, lookup_error, memory_gib, hardware_name):
    allocation = resolve_ollama_context(request, model_limit, running_limit, should_cancel=should_cancel)
    ceiling = allocation["contextCeiling"]
    if ceiling is None:
        output = deps.draft_output_tokens_for_characters(target_characters)
        maximum = deps.max_draft_chunk_characters(output, max_characters=target_characters)
        return {"provider": "ollama", **allocation, "promptTokenEstimate": prompt_estimate,
                "outputTokenLimit": output, "maxChunkCharacters": maximum,
                "predictedCalls": max(1, math.ceil(target_characters / max(1, maximum))),
                "estimatedResentTokens": None, "adaptiveLongForm": adaptive_long_form,
                "fallbackReason": lookup_error or "Ollama Cloudのためローカル実割当Context確認を省略",
                "detectedMemoryGiB": memory_gib, "hardwareName": hardware_name}
    available = ceiling - prompt_estimate - deps.DRAFT_CONTEXT_SAFETY_MARGIN
    if available < 256:
        raise DraftContextError(f"固定必須入力の見積もり{prompt_estimate} tokenと安全余白がContext {ceiling} tokenへ収まりません。")
    maximum = deps.max_draft_chunk_characters(available, max_characters=target_characters)
    calls = max(1, math.ceil(target_characters / max(1, maximum)))
    return {"provider": "ollama", **allocation, "promptTokenEstimate": prompt_estimate,
            "outputTokenLimit": available, "maxChunkCharacters": maximum,
            "predictedCalls": calls, "estimatedResentTokens": (calls - 1) * prompt_estimate,
            "adaptiveLongForm": adaptive_long_form, "fallbackReason": lookup_error or "Ollamaの実割当と明示カード設定を適用",
            "detectedMemoryGiB": memory_gib, "hardwareName": hardware_name}


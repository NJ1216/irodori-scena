from __future__ import annotations

from server.app_deps import Any, json, math, sys
from types import SimpleNamespace
from server.modules.draft_direction_capability import build_direction_capability_profile_impl
from server.modules.draft_context_recovery import reduce_ollama_context as reduce_ollama_context
from server.modules.draft_runtime_probe import (
    local_hardware_name,
    local_memory_gib,
    ollama_api_root as ollama_api_root,
    ollama_runtime_details,
)
from server.modules.draft_capability_limits import (
    configured_model_limit as _configured_model_limit,
    target_context_for_memory,
)
from server.registry import deps
from server.modules.ollama_context import (
    is_ollama_cloud_model,
    ollama_draft_profile,
    prepare_pinned_call,
    resolve_ollama_context,
)


def build_direction_capability_profile(request: Any) -> dict[str, Any]:
    runtime = SimpleNamespace(
        local_memory_gib=local_memory_gib,
        target_context_for_memory=target_context_for_memory,
        configured_model_limit=_configured_model_limit,
        ollama_runtime_details=ollama_runtime_details,
        resolve_ollama_context=resolve_ollama_context,
        direction_chunk_size_for_context=direction_chunk_size_for_context,
    )
    return build_direction_capability_profile_impl(request, runtime)


def direction_chunk_size_for_context(context: int) -> int:
    if context >= 32768:
        return 30
    if context >= 16384:
        return 20
    if context >= 8192:
        return 10
    if context >= 4096:
        return 5
    return 1


def select_direction_context(profile: dict[str, Any], *, input_tokens: int, output_tokens: int) -> int | None:
    """Select the smallest runtime tier that fits this actual request estimate."""
    ceiling = profile.get("contextCeiling")
    if not isinstance(ceiling, int):
        profile["effectiveContext"] = None
        return None
    required = input_tokens + output_tokens + 1024
    selected = next((tier for tier in (4096, 8192, 16384, 32768) if tier >= required and tier <= ceiling), None)
    profile["effectiveContext"] = selected
    profile["promptTokenEstimate"] = input_tokens
    profile["outputTokenLimit"] = output_tokens
    return selected


def estimate_llm_input_tokens(system: str, user: dict[str, Any]) -> int:
    """Conservative tokenizer-independent estimate from the exact request text."""
    characters = len(system) + len(json.dumps(user, ensure_ascii=False, separators=(",", ":")))
    return max(256, math.ceil(characters * 1.15) + 128)


def select_call_context(
    request: Any,
    *,
    system: str,
    user: dict[str, Any],
    max_tokens: int,
) -> dict[str, Any]:
    """Plan a single LLM call without persisting or changing a model card."""
    profile = build_direction_capability_profile(request)
    profile.pop("directionChunkSize", None)
    profile["feature"] = "single-call"
    input_tokens = estimate_llm_input_tokens(system, user)
    selected = select_direction_context(profile, input_tokens=input_tokens, output_tokens=max_tokens)
    profile["requiredTokens"] = input_tokens + max_tokens + 1024
    profile["predictedCalls"] = 1
    profile["estimatedResentTokens"] = 0
    if profile.get("contextCeiling") is not None and selected is None:
        raise RuntimeError("LLM要求が利用可能なContext上限へ収まりません。入力または応答上限を短くしてください。")
    return profile


def validate_external_call_context(*, system: str, user: dict[str, Any], max_tokens: int) -> None:
    """Fail before network I/O when a card-declared OpenAI ceiling cannot fit the real prompt."""
    profile = active_draft_capability_profile()
    if not profile or profile.get("provider") != "openai" or not isinstance(profile.get("contextCeiling"), int):
        return
    required = estimate_llm_input_tokens(system, user) + max_tokens + deps.DRAFT_CONTEXT_SAFETY_MARGIN
    ceiling = int(profile["contextCeiling"])
    selected = next(
        (
            tier
            for tier in (4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576)
            if tier >= required and tier <= ceiling
        ),
        None,
    )
    if selected is None:
        raise RuntimeError(
            "LLM要求がモデルカードのContext上限へ収まりません。送信せず停止しました。"
            "モデルカードのContext上限を正しい値へ修正してください。"
        )
    profile["effectiveContext"] = selected
    profile["actualPromptTokenEstimate"] = required - max_tokens - deps.DRAFT_CONTEXT_SAFETY_MARGIN


def prepare_draft_llm_call(
    request: Any,
    *,
    system: str,
    user: dict[str, Any],
    max_tokens: int,
    feature: str,
) -> int:
    """Fit one exact serialized request before any provider network I/O."""
    profile = active_draft_capability_profile()
    if profile is None:
        profile = build_direction_capability_profile(request)
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = profile
    input_tokens = estimate_llm_input_tokens(system, user)
    ceiling = profile.get("contextCeiling")
    if isinstance(profile.get("jobContext"), int):
        return prepare_pinned_call(profile, input_tokens=input_tokens, max_tokens=max_tokens, feature=feature)
    if feature == "draft-dialogue" and profile.get("adaptiveLongForm") is True and not isinstance(ceiling, int):
        output_tokens = min(max_tokens, int(profile.get("providerOutputTokenLimit") or max_tokens))
        profile["actualPromptTokenEstimate"] = input_tokens
        profile["lastCall"] = {
            "feature": feature,
            "logicalProvider": profile.get("provider", request.provider),
            "contextCeiling": None,
            "selectedContext": None,
            "inputTokenEstimate": input_tokens,
            "outputTokenLimit": output_tokens,
            "safetyMargin": deps.DRAFT_CONTEXT_SAFETY_MARGIN,
            "shrinkReasons": [],
        }
        profile.setdefault("calls", []).append(profile["lastCall"])
        return output_tokens
    if not isinstance(ceiling, int):
        current_context = profile.get("effectiveContext")
        ceiling = int(current_context) if isinstance(current_context, int) else 8192
    tiers = [tier for tier in (4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576) if tier <= ceiling]
    if not tiers:
        tiers = [ceiling]
    minimum_output = 256
    fitting = [tier for tier in tiers if tier >= input_tokens + minimum_output + deps.DRAFT_CONTEXT_SAFETY_MARGIN]
    if not fitting:
        raise RuntimeError(
            "LLM要求の固定必須情報が利用可能なContext上限へ収まりません。互換性のあるモデルを選択してください。"
        )
    pinned = profile.get("dialogueContext") if feature == "draft-dialogue" else None
    current = profile.get("effectiveContext")
    preserve_current = not feature.startswith("draft-") and feature != "direction"
    if isinstance(pinned, int) and pinned not in fitting:
        raise RuntimeError("台詞継続要求が固定済みContextへ収まりません。互換性のあるモデルを選択してください。")
    dynamic_dialogue = feature == "draft-dialogue" and profile.get("adaptiveLongForm") is True
    reservation = (
        int(profile.get("outputTokenLimit", max_tokens))
        if dynamic_dialogue
        else deps.DRAFT_DIALOGUE_TOKEN_CEILING
        if feature == "draft-dialogue"
        else max_tokens
    )
    selected = (
        int(pinned)
        if isinstance(pinned, int) and pinned in fitting
        else (
            int(current)
            if preserve_current and isinstance(current, int) and current in fitting
            else next(
                (tier for tier in fitting if tier >= input_tokens + reservation + deps.DRAFT_CONTEXT_SAFETY_MARGIN),
                fitting[-1],
            )
        )
    )
    if feature == "draft-dialogue" and not isinstance(pinned, int):
        profile["dialogueContext"] = selected
    output_tokens = min(max_tokens, selected - input_tokens - deps.DRAFT_CONTEXT_SAFETY_MARGIN)
    reasons = ["Context残容量に合わせて出力上限を縮小"] if output_tokens < max_tokens else []
    call = {
        "feature": feature,
        "logicalProvider": profile.get("provider", request.provider),
        "contextCeiling": ceiling,
        "selectedContext": selected,
        "inputTokenEstimate": input_tokens,
        "outputTokenLimit": output_tokens,
        "safetyMargin": deps.DRAFT_CONTEXT_SAFETY_MARGIN,
        "shrinkReasons": reasons,
    }
    profile["effectiveContext"] = selected
    profile["actualPromptTokenEstimate"] = input_tokens
    profile["lastCall"] = call
    profile.setdefault("calls", []).append(call)
    return output_tokens


def _prompt_token_estimate(request: deps.DraftRequest, characters: list[dict[str, Any]] | None) -> int:
    chars = len(request.theme) + sum(
        len(str(item.get("name", ""))) + len(str(item.get("profile", ""))) for item in characters or []
    )
    return max(deps.DRAFT_PROMPT_TOKEN_ESTIMATE_FLOOR, math.ceil(chars * 1.1) + 768)


def build_draft_capability_profile(
    request: deps.DraftRequest,
    characters: list[dict[str, Any]] | None = None,
    *,
    adaptive_long_form: bool = False,
    should_cancel=None,
) -> dict[str, Any]:
    """Compute one non-persistent capability profile for an AI draft job."""
    memory_gib = local_memory_gib()
    hardware_name = local_hardware_name()
    prompt_estimate = _prompt_token_estimate(request, characters)
    logical = deps.resolve_logical_llm_request(request)
    target_characters = max(160, round(request.target_minutes * 360 * request.speech_rate))
    if adaptive_long_form:
        target_characters = deps.draft_generation_target(target_characters)
    if logical.provider == "openai":
        capabilities = deps.resolve_llm_capabilities(logical.provider, logical.base_url, logical.model)
        provider_output = capabilities.get("outputTokenLimit")
        provider_output = provider_output if isinstance(provider_output, int) and provider_output > 0 else None
        setting = deps.resolve_llm_settings(logical.provider, logical.base_url, logical.model).get("contextLimit")
        if not isinstance(setting, int) or isinstance(setting, bool):
            discovered = capabilities.get("inputTokenLimit")
            setting = discovered if isinstance(discovered, int) and not isinstance(discovered, bool) else None
        if not isinstance(setting, int) or isinstance(setting, bool):
            if adaptive_long_form:
                output = min(provider_output or sys.maxsize, deps.draft_output_tokens_for_characters(target_characters))
                maximum = deps.max_draft_chunk_characters(output, max_characters=target_characters)
                return {
                    "provider": logical.provider,
                    "effectiveContext": None,
                    "contextCeiling": None,
                    "contextApplied": False,
                    "promptTokenEstimate": prompt_estimate,
                    "outputTokenLimit": output,
                    "providerOutputTokenLimit": provider_output,
                    "maxChunkCharacters": maximum,
                    "predictedCalls": max(1, math.ceil(target_characters / maximum)),
                    "estimatedResentTokens": None,
                    "fallbackReason": "Context上限不明のためprovider出力上限と要求量から計画",
                    "detectedMemoryGiB": memory_gib,
                    "hardwareName": hardware_name,
                    "adaptiveLongForm": True,
                }
            return {
                "provider": logical.provider,
                "effectiveContext": 8192,
                "contextCeiling": 8192,
                "contextApplied": False,
                "outputTokenLimit": 8192,
                "maxChunkCharacters": 2500,
                "promptTokenEstimate": prompt_estimate,
                "fallbackReason": "一般OpenAI互換にはContext指定を送信しない",
                "detectedMemoryGiB": memory_gib,
                "hardwareName": hardware_name,
                "predictedCalls": None,
                "estimatedResentTokens": None,
            }
        planned = deps.select_draft_job_context(
            ceiling=setting,
            prompt_tokens=prompt_estimate,
            target_characters=target_characters,
            minimize_calls=True,
            dynamic_output=adaptive_long_form,
            provider_output_ceiling=provider_output,
        )
        return {
            "provider": logical.provider,
            "cardContextLimit": setting,
            "contextCeiling": setting,
            "contextApplied": False,
            "promptTokenEstimate": prompt_estimate,
            "fallbackReason": "モデルカードのContext上限を内部適合判定へ適用（APIへは未送信）",
            "detectedMemoryGiB": memory_gib,
            "hardwareName": hardware_name,
            "adaptiveLongForm": adaptive_long_form,
            "providerOutputTokenLimit": provider_output,
            **planned,
        }
    if logical.provider not in {"ollama", "lmstudio", "scena-local"}:
        if adaptive_long_form:
            capabilities = deps.resolve_llm_capabilities(logical.provider, logical.base_url, logical.model)
            limit = capabilities.get("outputTokenLimit")
            limit = limit if isinstance(limit, int) and limit > 0 else None
            output = min(limit or sys.maxsize, deps.draft_output_tokens_for_characters(target_characters))
            maximum = deps.max_draft_chunk_characters(output, max_characters=target_characters)
            return {
                "provider": logical.provider,
                "effectiveContext": None,
                "contextCeiling": None,
                "contextApplied": False,
                "promptTokenEstimate": prompt_estimate,
                "outputTokenLimit": output,
                "providerOutputTokenLimit": limit,
                "maxChunkCharacters": maximum,
                "predictedCalls": max(1, math.ceil(target_characters / maximum)),
                "estimatedResentTokens": None,
                "fallbackReason": "Context上限不明のためprovider出力上限と要求量から計画",
                "detectedMemoryGiB": memory_gib,
                "hardwareName": hardware_name,
                "adaptiveLongForm": True,
            }
        return {
            "provider": logical.provider,
            "effectiveContext": 8192,
            "contextCeiling": 8192,
            "contextApplied": False,
            "outputTokenLimit": 8192,
            "maxChunkCharacters": 2500,
            "promptTokenEstimate": prompt_estimate,
            "fallbackReason": "一般OpenAI互換にはContext指定を送信しない",
            "detectedMemoryGiB": memory_gib,
            "hardwareName": hardware_name,
            "predictedCalls": None,
            "estimatedResentTokens": None,
        }
    card_limit = None
    if logical.provider == "lmstudio":
        model_limit, running_limit, lookup_error = deps.lmstudio_runtime_details(logical)
    elif logical.provider == "ollama":
        model_limit, running_limit, lookup_error = ollama_runtime_details(logical)
    else:
        selected = deps.resolve_default_llm()
        model_limit = _configured_model_limit({**selected, "settings": {}})
        card_limit = _configured_model_limit({"settings": selected.get("settings"), "localMetadata": {}})
        running_limit, lookup_error = None, None
        if sys.platform == "win32":
            deps.load_local_llm(selected["model"], settings=selected.get("settings") or {})
            runtime = deps.local_llm_status()
            running_limit = runtime.get("contextSize")
            if not isinstance(running_limit, int):
                raise RuntimeError("内蔵LLMの実割当Contextを確認できません。モデル起動前に停止しました。")
    if logical.provider == "ollama":
        return ollama_draft_profile(
            logical,
            model_limit,
            running_limit,
            prompt_estimate=prompt_estimate,
            target_characters=target_characters,
            adaptive_long_form=adaptive_long_form,
            should_cancel=should_cancel,
            lookup_error=lookup_error,
            memory_gib=memory_gib,
            hardware_name=hardware_name,
        )
    # A running local server has already admitted and allocated its configured
    # context.  When host-memory discovery is unavailable (notably restricted
    # Windows sessions), trust that runtime evidence instead of silently
    # collapsing a user-configured 32K Ollama context to the 4K fallback.
    requested = (
        running_limit
        if logical.provider == "scena-local" and sys.platform == "win32" and isinstance(running_limit, int)
        else min(32768, running_limit)
        if memory_gib is None and isinstance(running_limit, int) and running_limit >= 4096
        else target_context_for_memory(memory_gib)
    )
    known_limits = [value for value in (model_limit, card_limit, running_limit) if isinstance(value, int)]
    ceiling = (
        min([requested, *known_limits]) if known_limits else (requested if logical.provider == "scena-local" else 4096)
    )
    planned = deps.select_draft_job_context(
        ceiling=ceiling,
        prompt_tokens=prompt_estimate,
        target_characters=target_characters,
        minimize_calls=adaptive_long_form,
        dynamic_output=adaptive_long_form,
    )
    reasons = [
        reason
        for reason in [
            lookup_error,
            "モデルの最大コンテキストに合わせて縮小" if model_limit and model_limit < requested else "",
            "モデルカードのコンテキスト上限に合わせて縮小" if card_limit and card_limit < requested else "",
            "実行中モデルのコンテキストに合わせて縮小" if running_limit and running_limit < requested else "",
        ]
        if reason
    ]
    return {
        "provider": logical.provider,
        "modelContextLimit": model_limit,
        "cardContextLimit": card_limit,
        "runningContext": running_limit,
        "requestedContext": requested,
        "contextCeiling": ceiling,
        "promptTokenEstimate": prompt_estimate,
        "fallbackReason": "；".join(reasons),
        "detectedMemoryGiB": memory_gib,
        "hardwareName": hardware_name,
        "adaptiveLongForm": adaptive_long_form,
        **planned,
    }


def resolve_output_token_budget(request: deps.DraftRequest) -> int:
    return int(build_draft_capability_profile(request).get("outputTokenLimit", 8192))


def active_draft_capability_profile() -> dict[str, Any] | None:
    profile = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "capability_profile", None)
    return profile if isinstance(profile, dict) else None


def apply_ollama_context(payload: dict[str, Any], request: deps.DraftRequest) -> None:
    profile = active_draft_capability_profile()
    if profile is None and request.provider in {"ollama", "scena-local"}:
        messages = payload.get("messages", [])
        system = next((str(item.get("content", "")) for item in messages if item.get("role") == "system"), "")
        user_text = next((str(item.get("content", "")) for item in messages if item.get("role") == "user"), "{}")
        try:
            user = json.loads(user_text)
        except (TypeError, ValueError):
            user = {"input": user_text}
        profile = select_call_context(
            request,
            system=system,
            user=user if isinstance(user, dict) else {"input": user},
            max_tokens=int(payload.get("max_tokens", 0)),
        )
    if (
        request.provider == "ollama"
        and not is_ollama_cloud_model(request.model)
        and profile
        and isinstance(profile.get("effectiveContext"), int)
    ):
        payload["options"] = {"num_ctx": profile["effectiveContext"]}
    elif request.provider == "scena-local" and profile and isinstance(profile.get("effectiveContext"), int):
        # The SCENA-owned llama.cpp process fixes and verifies context at
        # startup; its OpenAI-compatible endpoint must not receive this
        # runtime-specific setting again.
        pass


deps.register(
    __name__,
    [
        "active_draft_capability_profile",
        "apply_ollama_context",
        "build_draft_capability_profile",
        "build_direction_capability_profile",
        "direction_chunk_size_for_context",
        "estimate_llm_input_tokens",
        "prepare_draft_llm_call",
        "select_call_context",
        "select_direction_context",
        "local_hardware_name",
        "local_memory_gib",
        "ollama_api_root",
        "ollama_runtime_details",
        "reduce_ollama_context",
        "resolve_output_token_budget",
        "target_context_for_memory",
        "validate_external_call_context",
    ],
)

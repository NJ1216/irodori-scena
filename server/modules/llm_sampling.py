from __future__ import annotations

from typing import Any, Literal

from server.registry import deps
from server.modules.anthropic_messages import is_anthropic_base_url


SamplingPolicy = Literal["creative", "deterministic"]


def resolve_sampling_settings(request: Any, temperature: float, policy: SamplingPolicy = "creative") -> dict[str, Any]:
    """Resolve effective values while the request still identifies its logical card."""
    provider = request.provider
    base_url = request.base_url
    if policy == "creative" and (not request.base_url or not request.model):
        selected = deps.resolve_default_llm()
        provider = selected["provider"]
        base_url = str(selected.get("baseUrl") or "")
        settings = selected.get("settings") or {}
    else:
        settings = deps.resolve_llm_settings(provider, request.base_url, request.model) if policy == "creative" else {}
    if provider == "openai" and is_anthropic_base_url(base_url):
        # Current Claude models and API version 2026-10-21 reject every sampling parameter.
        return {}
    resolved: dict[str, Any] = {"temperature": settings.get("temperature") if settings.get("temperature") is not None else temperature}
    if settings.get("topP") is not None:
        resolved["top_p"] = settings["topP"]
    if provider != "openai":
        for setting, field in (("topK", "top_k"), ("minP", "min_p"),
                               ("repetitionPenalty", "repeat_penalty")):
            if settings.get(setting) is not None:
                resolved[field] = settings[setting]
    return resolved


def apply_sampling_settings(payload: dict[str, Any], sampling: dict[str, Any]) -> None:
    payload.update(sampling)


deps.register(__name__, ["apply_sampling_settings", "resolve_sampling_settings"])

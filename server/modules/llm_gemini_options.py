"""Gemini compatibility options shared by probing and creative generation."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from server.registry import deps


def gemini_thinking_model(provider: str, model: str) -> bool:
    identity = model.removeprefix("models/").lower()
    return provider == "openai" and identity.startswith(("gemini-2.5-", "gemini-3"))


def google_gemini_endpoint(request: Any) -> bool:
    if not gemini_thinking_model(request.provider, request.model):
        return False
    try:
        url = urlsplit(request.base_url)
        return (url.scheme == "https" and url.hostname == "generativelanguage.googleapis.com"
                and url.port in {None, 443} and not url.username and not url.password
                and not url.query and not url.fragment
                and url.path.rstrip("/").removesuffix("/chat/completions") in {"/v1/openai", "/v1beta/openai"})
    except ValueError:
        return False


def gemini_reasoning_options(provider: str, model: str, *, thinking: bool = False) -> dict[str, str]:
    # "none" is invalid on Gemini 3 / 2.5 Pro. Low keeps reasoning available
    # without default high thinking exhausting small creative-output budgets.
    # https://ai.google.dev/gemini-api/docs/openai#thinking
    return {"reasoning_effort": "low"} if gemini_thinking_model(provider, model) and not thinking else {}


def prepare_gemini_payload(request: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Leave non-Google endpoints, explicit options and token budgets untouched."""
    if not google_gemini_endpoint(request) or "reasoning_effort" in payload:
        return payload
    settings = deps.resolve_llm_settings(request.provider, request.base_url, request.model)
    options = gemini_reasoning_options(request.provider, request.model, thinking=bool(settings.get("thinking")))
    return {**options, **payload}

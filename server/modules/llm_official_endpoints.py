"""Request options for the official OpenAI and Anthropic endpoints.

Both stay behind the shared OpenAI-shaped boundary. OpenAI's current chat models
take max_completion_tokens and reject some sampling values per model; a 400 that
names one such parameter is answered once by dropping it before any text is
generated. Anthropic defaults to low effort, matching the Gemini thinking policy.
"""
from __future__ import annotations

import json
import threading
from typing import Any
from urllib.parse import urlsplit

from server.registry import deps
from server.modules.anthropic_messages import effort_supported, is_anthropic_base_url

# Parameters SCENA may omit without changing what is asked; others are never dropped.
DROPPABLE_PARAMETERS = {"temperature", "top_p", "reasoning_effort", "seed", "presence_penalty",
                        "frequency_penalty", "stream_options"}
NON_CHAT_OPENAI_MODELS = ("embedding", "tts", "whisper", "dall-e", "moderation", "transcribe",
                          "gpt-image", "realtime", "davinci", "babbage", "sora")
# (parameter, rejected JSON value or None when the parameter itself is unsupported)
_REJECTED: dict[tuple[str, str], set[tuple[str, str | None]]] = {}
_LOCK = threading.Lock()


def is_openai_base_url(base_url: str) -> bool:
    try:
        url = urlsplit(str(base_url or "").strip())
    except (TypeError, ValueError):
        return False
    path = url.path.rstrip("/").removesuffix("/chat/completions").removesuffix("/models")
    return (url.scheme == "https" and url.hostname == "api.openai.com" and url.port in {None, 443}
            and not url.username and not url.password and path == "/v1")


def _key(request: Any) -> tuple[str, str]:
    return (str(getattr(request, "base_url", "")).rstrip("/"), str(getattr(request, "model", "")))


def _apply_rejected(request: Any, payload: dict[str, Any]) -> None:
    with _LOCK:
        rejected = set(_REJECTED.get(_key(request), set()))
    for parameter, value in rejected:
        if parameter not in payload or (value is not None and _value(payload[parameter]) != value):
            continue
        if parameter == "max_tokens":
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        else:
            payload.pop(parameter)


def _value(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def prepare_official_payload(request: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy adapted to the official endpoint; other endpoints only drop known rejections."""
    if getattr(request, "provider", None) != "openai":
        return payload
    payload = dict(payload)
    base_url = str(getattr(request, "base_url", ""))
    if is_openai_base_url(base_url) and "max_tokens" in payload:
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    elif is_anthropic_base_url(base_url) and "reasoning_effort" not in payload:
        settings = deps.resolve_llm_settings(request.provider, base_url, request.model)
        if not settings.get("thinking") and effort_supported(str(request.model)):
            payload["reasoning_effort"] = "low"
    _apply_rejected(request, payload)
    return payload


def adapt_rejected_parameter(request: Any, payload: dict[str, Any], status: int, detail: str) -> bool:
    """Drop or rename the single parameter an OpenAI-style 400 names; remember it for the model."""
    if getattr(request, "provider", None) != "openai" or status not in {400, 422}:
        return False
    try:
        error = json.loads(detail).get("error")
    except (ValueError, AttributeError):
        return False
    if not isinstance(error, dict) or error.get("code") not in {"unsupported_parameter", "unsupported_value"}:
        return False
    parameter = str(error.get("param") or "")
    if parameter not in payload or (parameter != "max_tokens" and parameter not in DROPPABLE_PARAMETERS):
        return False
    value = _value(payload[parameter]) if error["code"] == "unsupported_value" else None
    if parameter == "max_tokens":
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    else:
        payload.pop(parameter)
    with _LOCK:
        _REJECTED.setdefault(_key(request), set()).add((parameter, value))
    return True


def chat_model_ids(base_url: str, ids: list[str]) -> list[str]:
    if not is_openai_base_url(base_url):
        return ids
    return [item for item in ids if not any(marker in item.lower() for marker in NON_CHAT_OPENAI_MODELS)]


deps.register(__name__, ["adapt_rejected_parameter", "chat_model_ids", "is_openai_base_url",
                         "prepare_official_payload"])

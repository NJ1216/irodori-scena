"""Offline reference limits, not connection or structured-output guarantees.

Exact IDs and official endpoints only. K/M figures without an exact token count
are conservatively interpreted as decimal.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

VERIFIED_AT = "2026-09-05"
# Families re-checked after VERIFIED_AT keep their own date.
VERIFIED_AT_BY_FAMILY = {"claude": "2026-11-28"}

# family, exact IDs, context/input ceiling, output ceiling, official source
CATALOG = (
    ("gemini", ("gemini-2.5-pro",), 1048576, 65536,
     "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-pro"),
    ("gemini", ("gemini-2.5-flash",), 1048576, 65536,
     "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash"),
    ("gemini", ("gemini-2.5-flash-lite",), 1048576, 65536,
     "https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash-lite"),
    ("gemini", ("gemini-3-flash-preview",), 1048576, 65536,
     "https://ai.google.dev/gemini-api/docs/models/gemini-3-flash-preview"),
    ("gemini", ("gemini-3.1-pro-preview",), 1048576, 65536,
     "https://ai.google.dev/gemini-api/docs/models/gemini-3.1-pro-preview"),
    ("gemini", ("gemini-3.5-flash",), 1048576, 65536,
     "https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash"),
    ("openai", ("gpt-4.1", "gpt-4.1-2025-04-14"), 1047576, 32768,
     "https://developers.openai.com/api/docs/models/gpt-4.1"),
    ("openai", ("gpt-5.2", "gpt-5.2-2025-12-11"), 400000, 128000,
     "https://developers.openai.com/api/docs/models/gpt-5.2"),
    ("claude", ("claude-fable-5-2", "claude-fable-5-1", "claude-fable-5", "claude-mythos-5-2",
                "claude-mythos-5-1", "claude-mythos-5", "claude-opus-5-5", "claude-opus-5", "claude-opus-4-8",
                "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-5-5", "claude-sonnet-5",
                "claude-sonnet-4-6", "claude-haiku-5-5"), 1000000, 128000,
     "https://platform.claude.com/docs/en/models/overview"),
    ("claude", ("claude-haiku-4-5", "claude-haiku-4-5-20251001"), 200000, 64000,
     "https://platform.claude.com/docs/en/models/overview"),
    ("deepseek", ("deepseek-v4-flash", "deepseek-v4-pro"), 1000000, 384000,
     "https://api-docs.deepseek.com/quick_start/pricing/"),
    ("qwen", ("qwen3.5-plus", "qwen3.6-plus", "qwen3.7-plus"), 1000000, None,
     "https://www.alibabacloud.com/help/en/model-studio/coding-plan-faq"),
    ("glm", ("glm-4.7", "glm-4.7-flashx", "glm-4.7-flash"), 200000, 128000,
     "https://docs.z.ai/guides/llm/glm-4.7"),
    ("glm", ("glm-5",), 200000, 128000,
     "https://docs.z.ai/guides/llm/glm-5"),
    ("kimi", ("kimi-k3",), 1000000, None,
     "https://platform.kimi.ai/docs/models"),
    ("kimi", ("kimi-k2.7-code", "kimi-k2.7-code-highspeed", "kimi-k2.6"), 256000, None,
     "https://platform.kimi.ai/docs/models"),
)

# Paths are part of identity: a coding subscription or proxy is not the same
# service as a provider's standard endpoint, even on the same host.
ENDPOINTS = {
    ("generativelanguage.googleapis.com", "/v1beta/openai"): "gemini",
    ("generativelanguage.googleapis.com", "/v1/openai"): "gemini",
    ("api.openai.com", "/v1"): "openai",
    ("api.anthropic.com", ""): "claude",
    ("api.anthropic.com", "/v1"): "claude",
    ("api.deepseek.com", ""): "deepseek",
    ("api.deepseek.com", "/v1"): "deepseek",
    ("coding-intl.dashscope.aliyuncs.com", "/v1"): "qwen",
    ("api.z.ai", "/api/paas/v4"): "glm",
    ("api.moonshot.ai", "/v1"): "kimi",
}


def catalog_entry(family: str, model: str) -> dict[str, Any] | None:
    identity = model.removeprefix("models/") if family == "gemini" else model
    for entry_family, ids, context, output, url in CATALOG:
        if family == entry_family and identity in ids:
            return {"family": family, "modelId": identity, "inputTokenLimit": context,
                    "outputTokenLimit": output, "sourceUrl": url,
                    "verifiedAt": VERIFIED_AT_BY_FAMILY.get(family, VERIFIED_AT)}
    return None


def effective_capabilities(provider: str, base_url: str, model: str,
                           capabilities: dict[str, Any] | None) -> dict[str, Any]:
    """Fill unknown fields only; never persist reference values as measurements."""
    result = dict(capabilities or {})
    if provider != "openai":
        return result
    try:
        url = urlsplit(base_url)
        if url.scheme != "https" or url.port not in {None, 443} or url.username or url.password:
            return result
    except ValueError:
        return result
    family = ENDPOINTS.get((url.hostname, url.path.rstrip("/")))
    entry = catalog_entry(family or "", model)
    if entry is None:
        return result
    filled = []
    for key in ("inputTokenLimit", "outputTokenLimit"):
        value = result.get(key)
        if (type(value) is not int or value <= 0) and entry[key] is not None:
            result[key] = entry[key]
            filled.append(key)
    if filled:
        result["catalog"] = {**entry, "fields": filled}
        if len(filled) == 2 or result.get("source") in {None, "unknown"}:
            result["source"] = "catalog"
    return result

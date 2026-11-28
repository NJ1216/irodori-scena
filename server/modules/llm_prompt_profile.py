from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from server.registry import deps

PROMPT_PROTOCOL_VERSION = "scena-direction-cache-first-v4"
INTEGRATED_DRAFT_PROTOCOL_VERSION = "scena-integrated-draft-forward-v1"


def canonical_prompt_json(value: Any) -> str:
    """Serialize a deliberately ordered prompt without incidental whitespace."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# Prompt entries that stay the same for every call of one job. A prompt that opens with a run of
# them has a stable prefix a provider may cache; ordering is never changed to create one.
STABLE_PROMPT_ENTRIES = frozenset({
    "theme_or_situation", "request_settings", "participating_casts", "story_bible_and_global_outline",
    "character_id", "immutable_character_core", "author_idea",
})


def stable_prompt_prefix(content: str) -> str | None:
    """Return the leading text of a canonical prompt that holds only stable entries, if any.

    The prefix is cut from the serialized text itself and checked against it, so joining the
    prefix and the rest always gives back the exact original.
    """
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, dict) or not value:
        return None
    sections = value.get("sections") if len(value) == 1 else None
    if isinstance(sections, list):
        leading = []
        for section in sections:
            if not (isinstance(section, dict) and len(section) == 1 and next(iter(section)) in STABLE_PROMPT_ENTRIES):
                break
            leading.append(canonical_prompt_json(section))
        prefix = '{"sections":[' + ",".join(leading) + ","
    else:
        leading = []
        for key, item in value.items():
            if key not in STABLE_PROMPT_ENTRIES:
                break
            leading.append(canonical_prompt_json(key) + ":" + canonical_prompt_json(item))
        prefix = "{" + ",".join(leading) + ","
    if not leading or len(prefix) >= len(content) or not content.startswith(prefix):
        return None
    return prefix


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def cast_context_fingerprint(cast_context: Any) -> str | None:
    """Identify semantically identical compiled cast sheets across projects."""
    if not isinstance(cast_context, list) or not cast_context:
        return None
    canonical = json.dumps(cast_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(canonical)


def describe_llm_prompt(
    *, feature: str, system: str, user: dict[str, Any], max_tokens: int,
) -> dict[str, Any]:
    """Return content-free scope and size metadata for cache evidence."""
    user_json = canonical_prompt_json(user)
    sections = user.get("sections")
    section_values = {
        key: value for section in sections if isinstance(section, dict) for key, value in section.items()
    } if isinstance(sections, list) else user
    cast_context = section_values.get("participating_casts")
    cast_json = canonical_prompt_json(cast_context) if isinstance(cast_context, list) else ""
    cast_fingerprint = cast_context_fingerprint(cast_context)
    protocol_version = (
        INTEGRATED_DRAFT_PROTOCOL_VERSION if feature == "draft-dialogue" else PROMPT_PROTOCOL_VERSION
    )
    global_fingerprint = _digest(f"{protocol_version}\0{feature}\0{system}")
    stable_fingerprint = _digest(f"{global_fingerprint}\0{cast_json}") if cast_fingerprint else global_fingerprint
    return {
        "feature": feature,
        "protocolVersion": protocol_version,
        "scope": "cast" if cast_fingerprint else "global",
        "globalPrefixFingerprint": global_fingerprint,
        "stablePrefixFingerprint": stable_fingerprint,
        "castFingerprint": cast_fingerprint,
        "systemCharacters": len(system),
        "castCharacters": len(cast_json),
        "variableCharacters": max(0, len(user_json) - len(cast_json)),
        "inputTokenEstimate": deps.estimate_llm_input_tokens(system, user),
        "outputTokenLimit": max_tokens,
    }


def cache_metric_delta(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    """Compute selected monotonic oMLX counters without retaining runtime payloads."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {}
    keys = (
        "requests", "prompt_tokens", "completion_tokens", "cached_tokens",
        "prefill_duration", "generation_duration",
        "prefix_hits", "prefix_misses",
        "prefix_tokens_saved", "hot_cache_evictions", "ssd_saves",
    )
    result: dict[str, Any] = {}
    for key in keys:
        old, new = before.get(key), after.get(key)
        if isinstance(old, (int, float)) and not isinstance(old, bool) and isinstance(new, (int, float)) and not isinstance(new, bool):
            result[key] = max(0, new - old)
    prompt = result.get("prompt_tokens")
    cached = result.get("cached_tokens")
    if isinstance(prompt, (int, float)) and isinstance(cached, (int, float)):
        result["new_prefill_tokens"] = max(0, prompt - cached)
    for key in ("cache_block_size", "active_memory_bytes", "peak_memory_bytes"):
        value = after.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
    return result


def begin_llm_observation(
    request: Any, *, feature: str, system: str, user: dict[str, Any], max_tokens: int,
) -> dict[str, Any]:
    observation = describe_llm_prompt(
        feature=feature, system=system, user=user, max_tokens=max_tokens,
    )
    observation["provider"] = request.provider
    observation["model"] = request.model
    observation["startedAt"] = time.monotonic()
    observation["cacheBefore"] = (
        deps.local_llm_cache_metrics(request.model)
        if request.provider == "scena-local"
        else None
    )
    return observation


def finish_llm_observation(
    observation: dict[str, Any], *, response_path: Path | None, provider_tokens: int | None,
    provider_usage: dict[str, int] | None = None,
) -> None:
    after = (
        deps.local_llm_cache_metrics(str(observation["model"]))
        if observation.get("provider") == "scena-local"
        else None
    )
    details = {
        key: value for key, value in observation.items()
        if key not in {"startedAt", "cacheBefore"} and value is not None
    }
    details["wallClockSeconds"] = round(time.monotonic() - float(observation["startedAt"]), 6)
    usage = provider_usage or {}
    cache_delta = cache_metric_delta(observation.get("cacheBefore"), after)
    prompt = usage.get("promptTokens")
    cached = usage.get("cachedTokens")
    uncached = prompt - cached if isinstance(prompt, int) and isinstance(cached, int) else None
    prefill = cache_delta.get("prefill_duration")
    hits = cache_delta.get("prefix_hits")
    misses = cache_delta.get("prefix_misses")
    details["providerTokens"] = provider_tokens if provider_tokens is not None else "unavailable"
    details["providerUsage"] = usage or "unavailable"
    details["uncachedInputTokens"] = uncached if uncached is not None else cache_delta.get("new_prefill_tokens", "unavailable")
    details["prefillSeconds"] = prefill if prefill is not None else "unavailable"
    details["kvCacheHit"] = (
        hits > 0
        if isinstance(hits, (int, float)) and isinstance(misses, (int, float)) and hits + misses > 0
        else "unavailable"
    )
    details["cacheDelta"] = cache_delta or "unavailable"
    deps.write_llm_stream_diagnostic(response_path, "prompt_metrics", details=details)


deps.register(
    __name__,
    ["INTEGRATED_DRAFT_PROTOCOL_VERSION", "PROMPT_PROTOCOL_VERSION", "begin_llm_observation", "cache_metric_delta",
     "canonical_prompt_json", "cast_context_fingerprint", "describe_llm_prompt",
     "finish_llm_observation", "stable_prompt_prefix"],
)

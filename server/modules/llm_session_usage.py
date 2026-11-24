from __future__ import annotations

import math
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from server.registry import deps
from server.modules.llm_runtime_binding import serialized, require_generation_available

_SESSION_STARTED_AT = int(time.time() * 1000)
_LOCK = threading.RLock()
_OPERATIONS: dict[str, dict[str, Any]] = {}
_ORDER: list[str] = []
_CONTEXT = threading.local()
USAGE_TOTAL_FIELDS = ("inputTokens", "outputTokens", "totalTokens", "cachedInputTokens",
                      "unknownUsageCalls", "unconfirmedInputTokens", "unattributedTokens")


def _empty_usage() -> dict[str, Any]:
    return {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0, "cachedInputTokens": 0,
            "unknownUsageCalls": 0, "unconfirmedInputTokens": 0, "unattributedTokens": 0,
            "inputEstimated": False, "outputEstimated": False, "totalEstimated": False,
            "cachedInputEstimated": False}


def _classification(usage: dict[str, Any]) -> str:
    if usage.get("unknownUsageCalls"):
        return "partial"
    flags = [usage[key] for key in ("inputEstimated", "outputEstimated", "totalEstimated")]
    return "estimated" if all(flags) else "partial" if any(flags) else "reported"


def _operation_card(provider: str, model: str) -> tuple[str, str, dict[str, Any]]:
    registry = deps.read_llm_registry()
    endpoints = {x["id"]: x for x in registry["endpoints"]}
    if not provider or not model:
        card = next((x for x in registry["cards"] if x["id"] == registry["defaultCardId"]), {})
    else:
        card = next((x for x in registry["cards"] if x["modelId"] == model
                     and endpoints[x["endpointId"]]["provider"] == provider), {})
    endpoint = endpoints.get(card.get("endpointId"), {})
    return provider or endpoint.get("provider", ""), model or card.get("modelId", ""), card


def operation_llm_selection() -> dict[str, Any] | None:
    with _LOCK:
        operation = _OPERATIONS.get(getattr(_CONTEXT, "operation_id", None), {})
        card_id = operation.get("cardId")
    return deps.resolve_llm_card(card_id) if card_id else None


@serialized
def begin_llm_operation(operation_id: str, name: str, provider: str = "", model: str = "") -> None:
    with _LOCK:
        if operation_id in _OPERATIONS:
            return
        provider, model, card = _operation_card(provider, model)
        require_generation_available(provider)
        _OPERATIONS[operation_id] = {"id": operation_id, "name": name, "provider": provider, "model": model,
            "runtimeId": card.get("runtimeId"), "cardId": card.get("id"),
            "status": "running", "startedAt": int(time.time() * 1000), "completedAt": None,
            "callCount": 0, "usage": _empty_usage()}
        _ORDER.append(operation_id)
        while len(_ORDER) > 100:
            _OPERATIONS.pop(_ORDER.pop(0), None)


def finish_llm_operation(operation_id: str, status: str) -> None:
    with _LOCK:
        operation = _OPERATIONS.get(operation_id)
        if operation:
            operation.update(status=status, completedAt=int(time.time() * 1000))


def record_llm_call(*, operation_id: str | None, usage: dict[str, int] | int | None, input_estimate: int,
                    output_text: str, provider: str = "", model: str = "", failed: bool = False) -> dict[str, Any]:
    operation_id = operation_id or getattr(_CONTEXT, "operation_id", None)
    if not operation_id:
        return _empty_usage()
    begin_llm_operation(operation_id, getattr(_CONTEXT, "name", "LLM操作"), provider, model)
    reported = usage if isinstance(usage, dict) else ({"totalTokens": usage} if isinstance(usage, int) else {})
    input_tokens = reported.get("promptTokens", input_estimate)
    output_tokens = reported.get("completionTokens", math.ceil(len(output_text.encode("utf-8")) / 4) if output_text else 0)
    total_tokens = reported.get("totalTokens", input_tokens + output_tokens)
    call = {"inputTokens": input_tokens, "outputTokens": output_tokens, "totalTokens": total_tokens,
        "unknownUsageCalls": 0, "unconfirmedInputTokens": 0,
        "unattributedTokens": max(0, total_tokens - input_tokens - output_tokens) if all(
            key in reported for key in ("promptTokens", "completionTokens", "totalTokens")) else 0,
        "cachedInputTokens": reported.get("cachedTokens", 0), "inputEstimated": "promptTokens" not in reported,
        "outputEstimated": "completionTokens" not in reported, "totalEstimated": "totalTokens" not in reported,
        "cachedInputEstimated": "cachedTokens" not in reported}
    if failed and not reported:
        call = {**_empty_usage(), "unknownUsageCalls": 1, "unconfirmedInputTokens": input_estimate}
    with _LOCK:
        operation = _OPERATIONS[operation_id]
        operation["provider"] = provider or operation["provider"]
        operation["model"] = model or operation["model"]
        operation["callCount"] += 1
        for key in USAGE_TOTAL_FIELDS:
            operation["usage"][key] += call[key]
        for key in ("inputEstimated", "outputEstimated", "totalEstimated", "cachedInputEstimated"):
            operation["usage"][key] = operation["usage"][key] or call[key]
    return call


@contextmanager
def llm_operation(name: str) -> Iterator[str]:
    operation_id = f"operation_{time.time_ns()}"
    previous = (getattr(_CONTEXT, "operation_id", None), getattr(_CONTEXT, "name", None))
    _CONTEXT.operation_id, _CONTEXT.name = operation_id, name
    begin_llm_operation(operation_id, name)
    try:
        yield operation_id
    except BaseException as error:
        finish_llm_operation(operation_id, "cancelled" if type(error).__name__ == "GenerationCancelled" else "failed")
        raise
    else:
        finish_llm_operation(operation_id, "completed")
    finally:
        _CONTEXT.operation_id, _CONTEXT.name = previous


def session_usage() -> dict[str, Any]:
    with _LOCK:
        total = _empty_usage()
        history = []
        for operation_id in reversed(_ORDER):
            operation = _OPERATIONS[operation_id]
            item = {**operation, "usage": dict(operation["usage"])}
            item["classification"] = _classification(item["usage"])
            history.append(item)
            for key in USAGE_TOTAL_FIELDS:
                total[key] += item["usage"][key]
            for key in ("inputEstimated", "outputEstimated", "totalEstimated", "cachedInputEstimated"):
                total[key] = total[key] or item["usage"][key]
        return {"sessionStartedAt": _SESSION_STARTED_AT, "total": total,
                "classification": _classification(total), "history": history}


def reset_session_usage() -> dict[str, Any]:
    global _SESSION_STARTED_AT
    with _LOCK:
        _OPERATIONS.clear()
        _ORDER.clear()
        _SESSION_STARTED_AT = max(_SESSION_STARTED_AT + 1, int(time.time() * 1000))
    return session_usage()


deps.register(__name__, ["begin_llm_operation", "finish_llm_operation", "llm_operation", "record_llm_call",
                         "reset_session_usage", "session_usage", "operation_llm_selection"])

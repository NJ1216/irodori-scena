from __future__ import annotations

import email.utils
import json
import random
import math
import time
from dataclasses import dataclass
from typing import Callable

from server.app_deps import urllib
from server.registry import deps
from server.modules.anthropic_messages import MessagesResponse, outgoing_request
from server.modules.llm_gemini_options import prepare_gemini_payload
from server.modules.llm_official_endpoints import adapt_rejected_parameter, prepare_official_payload
from server.modules.llm_retry_budget import before_attempt, http_failure, reserve_retry

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


@dataclass
class TransportFailure(RuntimeError):
    category: str
    stage: str
    status: int | None = None
    partial_body: str = ""
    retry_after: float | None = None

    def __str__(self) -> str:
        labels = {
            "authentication": "認証に失敗しました。",
            "permission": "LLMの利用権限がありません。",
            "rate_limit": "利用上限に達しました。",
            "quota_exhausted": "日次の利用上限に達しました。生成済み内容を保持して停止します。",
            "retry_later": "接続先から長い待機時間が指定されたため停止しました。時間を置いてください。",
            "overloaded": "LLMが混雑しています。",
            "context_limit": "モデルのContext上限を超えました。設定を確認してください。",
            "timeout": f"{self.stage}でタイムアウトしました。",
            "connection": "LLMへ接続できません。",
            "invalid_response": "LLMから不正な応答を受信しました。",
            "unsupported_parameter": "モデルが送信parameterに対応していません。",
        }
        return labels.get(self.category, "LLM呼び出しに失敗しました。")


def classify_http_failure(status: int, detail: str, *, stage: str = "response") -> TransportFailure:
    folded = detail.casefold()
    if status == 401:
        category = "authentication"
    elif status == 403:
        category = "permission"
    elif status == 429:
        category = "rate_limit"
    elif status == 503:
        category = "overloaded"
    elif status in {400, 422} and any(value in folded for value in ("context", "token limit", "too many tokens")):
        category = "context_limit"
    elif status in {400, 422} and any(value in folded for value in ("unsupported", "unknown parameter")):
        category = "unsupported_parameter"
    else:
        category = "invalid_response"
    return TransportFailure(category, stage, status=status)


def retry_after_seconds(value: str | None, *, now: float | None = None) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
        return max(0.0, parsed) if math.isfinite(parsed) else None
    except ValueError:
        try:
            target = email.utils.parsedate_to_datetime(value).timestamp()
            return max(0.0, target - (time.time() if now is None else now))
        except (TypeError, ValueError, OverflowError):
            return None


def retry_delay(attempt: int, retry_after: float | None = None,
                *, random_value: Callable[[], float] = random.random) -> float:
    if retry_after is not None:
        return max(0.0, retry_after)
    return min(4.0, float(2 ** (attempt - 1))) + random_value() * 0.25


def publish_transport_retry(attempt: int, category: str, delay: float) -> None:
    job_id = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None)
    if not job_id:
        return
    reason = "利用上限" if category == "rate_limit" else "LLMの混雑" if category == "overloaded" else "通信エラー"
    deps.update_draft_job(job_id, message=f"{reason}のため{delay:.1f}秒後に再試行します…",
                          transportStatus={"attempt": attempt + 1, "reason": category, "waitSeconds": round(delay, 1)})


def cancellable_wait(seconds: float, should_cancel: Callable[[], bool] | None) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        deps._raise_if_draft_cancelled(should_cancel)
        time.sleep(max(0.0, min(0.1, deadline - time.monotonic())))


def is_retryable(error: BaseException, *, received_body: bool = False) -> bool:
    if received_body or isinstance(error, deps.GenerationCancelled):
        return False
    if isinstance(error, TransportFailure):
        if error.category in {"quota_exhausted", "retry_later"}:
            return False
        return error.status in RETRYABLE_STATUS or error.category in {"connection", "timeout"}
    return isinstance(error, (ConnectionError, OSError, TimeoutError))


def retry_or_raise(error: BaseException, attempt: int, should_cancel: Callable[[], bool] | None,
                   *, enabled: bool = True) -> None:
    if not enabled or attempt >= 4 or not is_retryable(error, received_body=bool(getattr(error, "partial_body", ""))):
        raise error
    retry_number = reserve_retry(error) or attempt
    delay = retry_delay(retry_number, getattr(error, "retry_after", None))
    publish_transport_retry(attempt, getattr(error, "category", "connection"), delay)
    cancellable_wait(delay, should_cancel)


def openai_nonstream_payload(request, endpoint: str, payload: dict, should_cancel) -> dict:
    """Send one non-stream completion with the shared four-attempt policy."""
    payload = prepare_official_payload(request, prepare_gemini_payload(request, payload))
    for attempt in range(1, 5):
        before_attempt(request, should_cancel)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            connection, response = deps.openai_http_post(
                endpoint, body=body, headers=deps.request_headers(request.api_key), should_cancel=should_cancel
            )
            try:
                response_body = response.read()
                deps._raise_if_draft_cancelled(should_cancel)
            finally:
                deps.close_openai_http_post(connection)
            if response.status < 400:
                try:
                    parsed = json.loads(response_body.decode("utf-8"))
                except ValueError as error:
                    raise TransportFailure("invalid_response", "response", status=response.status) from error
                if not isinstance(parsed, dict):
                    raise TransportFailure("invalid_response", "response", status=response.status)
                parsed["_transport_headers"] = {
                    str(key).lower(): str(value) for key, value in response.headers.items()
                }
                return parsed
            detail = response_body.decode("utf-8", errors="replace")
            if adapt_rejected_parameter(request, payload, response.status, detail):
                continue
            if response.status in {400, 422} and deps.reduce_ollama_context(
                deps.active_draft_capability_profile(), detail
            ):
                reserve_retry(deps.classify_http_failure(response.status, detail))
                deps.apply_ollama_context(payload, request)
                continue
            failure = http_failure(request, response.status, detail, response.headers.get("retry-after"))
            retry_or_raise(failure, attempt, should_cancel, enabled=request.provider != "scena-local")
        except deps.GenerationCancelled:
            raise
        except (OSError, ValueError) as error:
            if should_cancel and should_cancel():
                raise deps.GenerationCancelled("台本生成をキャンセルしました。") from error
            retry_or_raise(TransportFailure("connection", "connect"), attempt, should_cancel,
                           enabled=request.provider != "scena-local")
    raise RuntimeError("The LLM endpoint failed after four attempts.")


def probe_post(request, endpoint: str, payload: dict, *, timeout: int = 120) -> tuple[str, str]:
    """Send one probe; only a named unsupported parameter is adapted, never a failure."""
    payload = prepare_official_payload(request, prepare_gemini_payload(request, payload))
    while True:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        target, body, headers, anthropic_stream = outgoing_request(
            endpoint, body, deps.request_headers(request.api_key))
        call = urllib.request.Request(target, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(call, timeout=timeout) as raw:
                response = raw if anthropic_stream is None else MessagesResponse(raw, stream=anthropic_stream)
                warning = str(response.headers.get("Warning") or "") if hasattr(response, "headers") else ""
                return response.read().decode("utf-8"), warning
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            if not adapt_rejected_parameter(request, payload, error.code, detail):
                raise


def openai_probe_payload(request, endpoint: str, payload: dict, *, timeout: int = 120) -> dict:
    """Shared non-stream transport for the deliberately single-attempt model probe."""
    raw, _ = probe_post(request, endpoint, payload, timeout=timeout)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("The endpoint returned a non-object response.")
    return parsed


deps.register(__name__, [
    "TransportFailure", "cancellable_wait", "classify_http_failure", "is_retryable", "openai_nonstream_payload",
    "openai_probe_payload", "probe_post", "retry_after_seconds",
    "publish_transport_retry", "retry_delay", "retry_or_raise",
])

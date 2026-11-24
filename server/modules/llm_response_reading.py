"""Read non-streaming and streaming OpenAI-compatible completion responses."""
from __future__ import annotations

from typing import Any, Callable

from server.app_deps import Path, json, time
from server.registry import deps


def extract_total_tokens(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    total = usage.get("total_tokens")
    if isinstance(total, bool):
        return None
    if isinstance(total, int) and total >= 0:
        return total
    return None


def extract_usage_metrics(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict) or not isinstance(payload.get("usage"), dict):
        return {}
    usage = payload["usage"]
    details = usage.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, dict) else usage.get("cached_tokens")
    candidates = {
        "promptTokens": usage.get("prompt_tokens"),
        "completionTokens": usage.get("completion_tokens"),
        "cachedTokens": cached,
        "totalTokens": usage.get("total_tokens"),
    }
    return {key: value for key, value in candidates.items()
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0}


def _non_stream_response_content(
    response,
    on_progress: Callable[[str], None] | None,
    loop_detector: Callable[[str], str | None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[str, int | None]:
    response_payload = json.loads(response.read().decode("utf-8"))
    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = extract_usage_metrics(response_payload)
    if should_cancel and should_cancel():
        raise deps.GenerationCancelled("台本生成をキャンセルしました。")
    choice = response_payload["choices"][0]
    message = choice["message"]
    deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason = choice.get("finish_reason")
    deps.DRAFT_LLM_THREAD_CONTEXT.refusal = message.get("refusal")
    content = str(message.get("content") or "")
    if on_progress:
        on_progress(content)
    reason = loop_detector(content) if loop_detector else None
    if reason:
        raise deps.DraftStreamLoopError(reason, content)
    return content, extract_total_tokens(response_payload)

def _stream_response_content(
    response,
    *,
    on_progress: Callable[[str], None] | None,
    loop_detector: Callable[[str], str | None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[str, int | None]:
    content = ""
    last_reported_length = 0
    last_reported_at = 0.0
    last_loop_check_length = 0
    total_tokens: int | None = None
    try:
        for data in deps.openai_stream_data(response, should_cancel):
            try:
                event = json.loads(data)
                event_total_tokens = extract_total_tokens(event)
                if event_total_tokens is not None:
                    total_tokens = event_total_tokens
                event_usage = extract_usage_metrics(event)
                if event_usage:
                    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = event_usage
                choice = event.get("choices", [{}])[0]
                delta_payload = choice.get("delta", {})
                deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason = (
                    choice.get("finish_reason") or getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "finish_reason", None)
                )
                deps.DRAFT_LLM_THREAD_CONTEXT.refusal = (
                    delta_payload.get("refusal") or getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "refusal", None)
                )
                delta = delta_payload.get("content")
            except (json.JSONDecodeError, IndexError, TypeError, AttributeError):
                continue
            if not delta:
                continue
            content += str(delta)
            now = time.monotonic()
            if on_progress and (len(content) - last_reported_length >= 256 or now - last_reported_at >= 0.25):
                on_progress(content)
                last_reported_length = len(content)
                last_reported_at = now
            if loop_detector and len(content) - last_loop_check_length >= 256:
                last_loop_check_length = len(content)
                reason = loop_detector(content)
                if reason:
                    raise deps.DraftStreamLoopError(reason, content)
    except (OSError, TimeoutError) as error:
        if content:
            if on_progress:
                on_progress(content)
            raise deps.TransportFailure("connection", "stream", partial_body=content) from error
        raise
    return content, total_tokens

def _read_text_completion_response(
    response,
    *,
    on_progress: Callable[[str], None] | None,
    loop_detector: Callable[[str], str | None] | None,
    should_cancel: Callable[[], bool] | None,
) -> tuple[str, int | None]:
    if response.status >= 400:
        detail = response.read().decode("utf-8", errors="replace")
        failure = deps.classify_http_failure(response.status, detail)
        retry_after = deps.retry_after_seconds(response.headers.get("retry-after"))
        raise deps.TransportFailure(failure.category, failure.stage, status=response.status, retry_after=retry_after)
    content_type = str(response.headers.get("content-type", "")).lower()
    if "text/event-stream" not in content_type:
        return _non_stream_response_content(response, on_progress, loop_detector, should_cancel)
    return _stream_response_content(
        response, on_progress=on_progress,
        loop_detector=loop_detector, should_cancel=should_cancel,
    )
def _lmstudio_stream_result(
    request: deps.DraftRequest, *, system: str, user: dict[str, Any], max_tokens: int, temperature: float,
    debug_response_path: Path | None, on_progress: Callable[[str], None] | None,
    loop_detector: Callable[[str], str | None] | None, should_cancel: Callable[[], bool] | None,
    job_id: str | None, sampling: dict[str, Any],
) -> str:
    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    deps.DRAFT_LLM_THREAD_CONTEXT.last_provider_usage = None
    if debug_response_path is not None:
        deps.write_draft_debug_request(debug_response_path, request=request, system=system, user=user, max_tokens=max_tokens, sampling=sampling)
    content = ""
    usage: int | None = None
    try:
        profile = deps.active_draft_capability_profile()
        before = profile.get("effectiveContext") if profile else None
        try:
            content, usage = deps.lmstudio_stream_text_completion(request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, on_progress=on_progress, loop_detector=loop_detector, should_cancel=should_cancel)
        except RuntimeError:
            if not profile or profile.get("effectiveContext") == before:
                raise
            content, usage = deps.lmstudio_stream_text_completion(request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, on_progress=on_progress, loop_detector=loop_detector, should_cancel=should_cancel)
    finally:
        metrics = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None)
        deps.record_draft_llm_usage(job_id, metrics if isinstance(metrics, dict) and metrics else usage,
                                    input_estimate=deps.estimate_llm_input_tokens(system, user), output_text=content,
                                    provider=request.provider, model=request.model)
        if debug_response_path is not None:
            deps.write_draft_debug_response(debug_response_path, content)
    if on_progress:
        on_progress(content)
    if not content.strip():
        raise RuntimeError("LM Studio native v1 API は本文を返しませんでした。")
    return content

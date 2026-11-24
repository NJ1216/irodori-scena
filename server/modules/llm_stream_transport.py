from __future__ import annotations

from server.app_deps import Any, Callable, json, time, Path
from server.registry import deps
from server.modules.llm_gemini_options import google_gemini_endpoint, prepare_gemini_payload
from server.modules.llm_retry_budget import before_attempt, current_budget, http_failure, reserve_retry


def openai_stream_data(response, should_cancel):
    """Yield SSE data until the provider's completion marker, independently of EOF."""
    for raw_line in response:
        deps._raise_if_draft_cancelled(should_cancel)
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        if data:
            yield data


def write_llm_stream_diagnostic(response_path: Path | None, event: str, *, details: dict[str, Any] | None = None) -> None:
    """Append secret-free lifecycle evidence beside one raw LLM response."""
    if response_path is None or not deps.LLM_DEBUG_ENABLED:
        return
    payload: dict[str, Any] = {"atMs": int(time.time() * 1000), "event": event}
    if details:
        payload.update(details)
    diagnostic_path = response_path.with_suffix(".events.jsonl")
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    with diagnostic_path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        output.write("\n")


def notify_llm_acceptance(
    hook: Callable[[dict[str, Any]], None] | None, *, attempt: int, received_characters: int,
    accepted_records: int, missing_targets: int, provider_tokens: int | None, accepted_characters: int,
) -> None:
    """Publish secret-free logical-attempt metrics for a future progress surface."""
    if hook is None:
        return
    hook({
        "attempt": attempt,
        "receivedCharacters": received_characters,
        "acceptedRecords": accepted_records,
        "missingTargets": missing_targets,
        "providerTokens": provider_tokens,
        "acceptedCharactersPerToken": (
            accepted_characters / provider_tokens if provider_tokens and provider_tokens > 0 else None
        ),
    })


def openai_stream_response(request: Any, *, endpoint: str, payload: dict[str, Any], debug_response_path: Path | None,
                           on_progress: Callable[[str], None] | None, loop_detector: Callable[[str], str | None] | None,
                           should_cancel: Callable[[], bool] | None, read_response: Callable[..., tuple[str, int | None]]) -> tuple[str, int | None]:
    """Apply bounded transport retries only until response text starts."""
    payload = prepare_gemini_payload(request, payload)
    request_usage = request.provider in {"openai", "ollama"}
    budget = current_budget()
    fallback_nonstream = bool(budget and request.base_url in budget.nonstream)
    for attempt in range(1, 5):
        before_attempt(request, should_cancel)
        started_at = time.monotonic()
        write_llm_stream_diagnostic(debug_response_path, "request_started", details={
            "attempt": attempt, "provider": request.provider, "model": request.model, "maxTokens": payload["max_tokens"],
        })
        stream_payload = dict(payload)
        if fallback_nonstream:
            stream_payload["stream"] = False
            stream_payload.pop("stream_options", None)
        elif request_usage:
            stream_payload["stream_options"] = {"include_usage": True}
        body = json.dumps(stream_payload, ensure_ascii=False).encode("utf-8")
        connection = None
        try:
            connection, response = deps.openai_http_post(
                endpoint, body=body, headers=deps.request_headers(request.api_key), should_cancel=should_cancel
            )
            deps.DRAFT_LLM_THREAD_CONTEXT.response_headers = {
                str(key).lower(): str(value) for key, value in response.headers.items()
            }
            write_llm_stream_diagnostic(debug_response_path, "response_headers_received", details={
                "attempt": attempt, "status": response.status, "contentType": str(response.headers.get("content-type", "")),
                "headerWaitSeconds": round(time.monotonic() - started_at, 6),
            })
            if response.status in {400, 422}:
                detail = response.read().decode("utf-8", errors="replace")
                if request_usage and any(marker in detail.casefold() for marker in ("stream_options", "include_usage")):
                    reserve_retry(deps.classify_http_failure(response.status, detail))
                    request_usage = False
                    continue
                if deps.reduce_ollama_context(deps.active_draft_capability_profile(), detail):
                    reserve_retry(deps.classify_http_failure(response.status, detail))
                    deps.apply_ollama_context(payload, request)
                    continue
                raise deps.classify_http_failure(response.status, detail)
            if response.status >= 400:
                detail = response.read().decode("utf-8", errors="replace")
                raise http_failure(request, response.status, detail, response.headers.get("retry-after"))
            result = read_response(response, on_progress=on_progress, loop_detector=loop_detector, should_cancel=should_cancel)
            write_llm_stream_diagnostic(debug_response_path, "request_finished", details={
                "attempt": attempt, "totalSeconds": round(time.monotonic() - started_at, 6),
            })
            return result
        except Exception as error:
            partial = getattr(error, "partial_body", "")
            if not deps.is_retryable(error, received_body=bool(partial)) or attempt >= 4:
                raise
            category = getattr(error, "category", "connection")
            retry_number = reserve_retry(error) or attempt
            if not fallback_nonstream and getattr(error, "status", None) == 503 and google_gemini_endpoint(request):
                fallback_nonstream = True
                if budget:
                    budget.nonstream.add(request.base_url)
                write_llm_stream_diagnostic(debug_response_path, "nonstream_fallback", details={
                    "attempt": attempt, "reason": "stream_http_503",
                })
            delay = deps.retry_delay(retry_number, getattr(error, "retry_after", None))
            write_llm_stream_diagnostic(debug_response_path, "request_retrying", details={
                "attempt": attempt, "category": getattr(error, "category", "connection"), "delaySeconds": delay,
            })
            deps.publish_transport_retry(attempt, category, delay)
            deps.cancellable_wait(delay, should_cancel)
        finally:
            if connection is not None:
                deps.close_openai_http_post(connection)
    raise RuntimeError("The LLM endpoint failed after four attempts.")


deps.register(__name__, ["notify_llm_acceptance", "openai_stream_data", "openai_stream_response", "write_llm_stream_diagnostic"])

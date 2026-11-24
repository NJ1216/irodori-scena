from __future__ import annotations

import re

from server.app_deps import Any, Callable, HTTPException, Path, http, json, os, time
from server.registry import deps
from server.modules.windows_external_memory import windows_accelerator_handoff


NATIVE_FLAG = "SCENA_EXPERIMENTAL_OLLAMA_NATIVE_CHAT"
_THINK_OPEN = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE = re.compile(
    r"</think\s*>|<channel\|>|<\|final\|>|<\|end_think\|>|<\|channel\|>final[ \t]*\r?\n", re.IGNORECASE)


def _possible_think_prefix(value: str) -> bool:
    return any(stem.startswith(value) for stem in ("<think", "</think", "<channel|>"))


def _truncated_think_tag(value: str) -> bool:
    for stem in ("<think", "</think"):
        if value == stem:
            return True
        if value.startswith(stem) and len(value) > len(stem) and value[len(stem)] in " \t\r\n/>":
            return True
    return False


def ollama_native_enabled(request: Any) -> bool:
    """Draft jobs share native settings across structured and plain responses."""
    draft_job = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None)
    return request.provider == "ollama" and (bool(draft_job) or os.environ.get(NATIVE_FLAG, "").strip() == "1")


def ollama_structured_enabled(request: Any) -> bool:
    """Structured output always uses Ollama's documented native chat route."""
    return request.provider == "ollama"


def _keep_alive(request: Any) -> str | int:
    settings = deps.resolve_llm_settings(request.provider, request.base_url, request.model)
    value = settings.get("ttlSeconds", 300)
    try:
        seconds = max(0, min(86400, int(value)))
    except (TypeError, ValueError):
        seconds = 300
    return 0 if seconds == 0 else f"{seconds}s"


def _payload(request: Any, *, system: str, user: dict[str, Any], max_tokens: int,
             sampling: dict[str, Any], stream: bool, format_schema: dict[str, Any] | None = None,
             benchmark_seed: int | None = None) -> dict[str, Any]:
    options = dict(sampling)
    options["num_predict"] = max_tokens
    if benchmark_seed is not None:
        options["seed"] = benchmark_seed
    profile = deps.active_draft_capability_profile() or deps.select_call_context(
        request, system=system, user=user, max_tokens=max_tokens,
    )
    if isinstance(profile, dict) and isinstance(profile.get("effectiveContext"), int):
        options["num_ctx"] = profile["effectiveContext"]
    payload = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": deps.canonical_prompt_json(user)},
        ],
        "stream": stream,
        "think": False,
        "keep_alive": _keep_alive(request),
        "options": options,
    }
    if format_schema is not None:
        payload["format"] = format_schema
    return payload


class OllamaContentSanitizer:
    """Incrementally suppress reasoning wrappers without exposing split prefixes."""

    def __init__(self) -> None:
        self.pending = ""
        self.thinking = False
        self.removed_controls: dict[str, int] = {}
        self.suppressed_blocks = 0

    def control(self) -> bool:
        closing = self.pending.find(">")
        if closing < 0:
            return False
        token = self.pending[:closing + 1].casefold()
        remaining = self.pending[closing + 1:]
        if token in {"<|channel>", "<|channel|>"}:
            boundary = remaining.find("\n")
            if boundary < 0:
                return False
            channel = remaining[:boundary].strip().casefold()
            # Unknown channels have no unambiguous creative destination.
            self.thinking = channel not in {"final", "answer", "response"}
            remaining = remaining[boundary + 1:]
        elif token in {"<|analysis|>", "<|think|>"}:
            self.thinking = True
        self.suppressed_blocks += int(self.thinking)
        self.removed_controls[token] = self.removed_controls.get(token, 0) + 1
        self.pending = remaining
        return True

    def feed(self, value: Any) -> str:
        self.pending += str(value or "")
        output: list[str] = []
        while self.pending:
            if self.thinking:
                closing = _THINK_CLOSE.search(self.pending)
                if closing is None:
                    return "".join(output)
                self.pending = self.pending[closing.end():]
                self.thinking = False
                continue
            marker = self.pending.find("<")
            if marker < 0:
                output.append(self.pending)
                self.pending = ""
                break
            if marker:
                output.append(self.pending[:marker])
                self.pending = self.pending[marker:]
                continue
            opening = _THINK_OPEN.match(self.pending)
            if opening:
                self.pending = self.pending[opening.end():]
                self.thinking = True
                self.suppressed_blocks += 1
                continue
            closing = _THINK_CLOSE.match(self.pending)
            if closing:
                self.pending = self.pending[closing.end():]
                continue
            lowered = self.pending.casefold()
            if _possible_think_prefix(lowered) or _truncated_think_tag(lowered):
                return "".join(output)
            if lowered.startswith("<|"):
                if not self.control():
                    return "".join(output)
                continue
            if lowered in {"<", "</"}:
                return "".join(output)
            output.append("<")
            self.pending = self.pending[1:]
        return "".join(output)

    def finish(self) -> str:
        output = self.feed("")
        lowered = self.pending.casefold()
        if self.thinking or _truncated_think_tag(lowered) or lowered.startswith("<|"):
            self.pending = ""
            self.thinking = False
            return output
        output += self.pending
        self.pending = ""
        return output


def _metrics(payload: Any) -> dict[str, int | float | None]:
    source = payload if isinstance(payload, dict) else {}
    prompt = source.get("prompt_eval_count")
    generated = source.get("eval_count")
    prompt_ns = source.get("prompt_eval_duration")
    eval_ns = source.get("eval_duration")
    def seconds(value: Any) -> float | None:
        return value / 1_000_000_000 if type(value) is int and value >= 0 else None
    prompt_seconds, eval_seconds = seconds(prompt_ns), seconds(eval_ns)
    return {
        "promptTokens": prompt if type(prompt) is int and prompt >= 0 else None,
        "completionTokens": generated if type(generated) is int and generated >= 0 else None,
        "loadSeconds": seconds(source.get("load_duration")),
        "promptProcessingSeconds": prompt_seconds,
        "decodeSeconds": eval_seconds,
        "providerTotalSeconds": seconds(source.get("total_duration")),
        "promptTokensPerSecond": prompt / prompt_seconds if isinstance(prompt, int) and prompt_seconds else None,
        "tokensPerSecond": generated / eval_seconds if isinstance(generated, int) and eval_seconds else None,
    }


def _usage(metrics: dict[str, Any]) -> int | None:
    values = (metrics.get("promptTokens"), metrics.get("completionTokens"))
    return sum(values) if all(isinstance(value, int) for value in values) else None


def _record_metrics(job_id: str | None, metrics: dict[str, Any]) -> None:
    if job_id:
        deps.update_draft_job(job_id, ollamaNativeMetrics=metrics)


def _publish_native_delta(content, delta, on_progress, loop_detector):
    content += delta
    if on_progress:
        on_progress(content)
    reason = loop_detector(content) if loop_detector else None
    if reason:
        raise deps.DraftStreamLoopError(reason, content)
    return content


def _native_diagnostics(path, content, raw_events, final, payload, sanitizer):
    if path is None:
        return
    deps.write_draft_debug_response(path, content)
    deps.write_draft_debug_response(path.with_suffix(".events.jsonl"), "\n".join(raw_events))
    deps.write_draft_debug_response(path.with_suffix(".transport.json"), json.dumps({
        "done": bool(final), "doneReason": final.get("done_reason"),
        "finishReason": deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason,
        "receivedCharacters": len(content), "metrics": _metrics(final),
        "options": payload["options"], "think": payload["think"],
        "removedControlTokens": sanitizer.removed_controls,
        "suppressedReasoningBlocks": sanitizer.suppressed_blocks,
        "callBudget": (deps.active_draft_capability_profile() or {}).get("lastCall", {}),
    }, ensure_ascii=False, indent=2))


@windows_accelerator_handoff
def ollama_native_completion(
    request: Any, *, system: str, user: dict[str, Any], max_tokens: int, sampling: dict[str, Any],
    stream: bool, on_progress: Callable[[str], None] | None = None,
    loop_detector: Callable[[str], str | None] | None = None,
    should_cancel: Callable[[], bool] | None = None, job_id: str | None = None,
    format_schema: dict[str, Any] | None = None,
    benchmark_seed: int | None = None, debug_response_path: Path | None = None,
    feature: str = "llm-native", prepared: bool = False,
) -> tuple[str, int | None]:
    from server.modules.llm_retry_budget import before_attempt
    if not prepared:
        max_tokens = deps.prepare_draft_llm_call(request, system=system, user=user,
                                                max_tokens=max_tokens, feature=feature)
    payload = _payload(request, system=system, user=user, max_tokens=max_tokens,
                       sampling=sampling, stream=stream, format_schema=format_schema, benchmark_seed=benchmark_seed)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if debug_response_path is not None:
        deps.write_draft_debug_request(debug_response_path, request=request, system=system, user=user,
                                       max_tokens=max_tokens, sampling=payload["options"])
        deps.write_draft_debug_response(debug_response_path.with_suffix(".payload.json"),
                                        json.dumps(payload, ensure_ascii=False, indent=2))
    root = deps.ollama_api_root(request.base_url)
    connection = None
    content = ""
    final: dict[str, Any] = {}
    started = time.monotonic()
    first_content_at: float | None = None
    sanitizer = OllamaContentSanitizer()
    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    deps.DRAFT_LLM_THREAD_CONTEXT.last_provider_usage = None
    deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason = None
    deps.DRAFT_LLM_THREAD_CONTEXT.response_headers = {}
    deps.DRAFT_LLM_THREAD_CONTEXT.refusal = None
    deps.DRAFT_LLM_THREAD_CONTEXT.terminal_received = False
    raw_events: list[str] = []
    try:
        before_attempt(request, should_cancel)
        connection, response = deps.openai_http_post(
            f"{root}/api/chat", body=body, headers=deps.request_headers(request.api_key), should_cancel=should_cancel
        )
        if response.status >= 400:
            detail = response.read().decode("utf-8", errors="replace")
            deps.reduce_ollama_context(deps.active_draft_capability_profile(), detail)
            raise deps.classify_http_failure(response.status, detail)
        events = response if stream else [response.read()]
        for raw in events:
            deps._raise_if_draft_cancelled(should_cancel)
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            raw_events.append(decoded)
            if not decoded.strip():
                continue
            event = json.loads(decoded)
            message = event.get("message") if isinstance(event, dict) else None
            delta = sanitizer.feed(message.get("content")) if isinstance(message, dict) else ""
            if delta:
                first_content_at = first_content_at or time.monotonic()
                content = _publish_native_delta(content, delta, on_progress, loop_detector)
            if isinstance(event, dict) and event.get("done"):
                final = event
                deps.DRAFT_LLM_THREAD_CONTEXT.terminal_received = True
                deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason = str(event.get("done_reason") or "stop")
        tail = sanitizer.finish()
        if tail:
            content = _publish_native_delta(content, tail, on_progress, loop_detector)
        metrics = _metrics(final)
        finished = time.monotonic()
        metrics["ttftSeconds"] = (first_content_at or finished) - started
        metrics["wallClockSeconds"] = finished - started
        _record_metrics(job_id, metrics)
        prompt, completion = metrics.get("promptTokens"), metrics.get("completionTokens")
        if isinstance(prompt, int) and isinstance(completion, int):
            deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = {
                "promptTokens": prompt, "completionTokens": completion, "totalTokens": prompt + completion,
            }
            deps.DRAFT_LLM_THREAD_CONTEXT.last_provider_usage = deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage
        return content, _usage(metrics)
    except deps.GenerationCancelled:
        raise
    except (OSError, ValueError, http.client.HTTPException) as error:
        if should_cancel and should_cancel():
            raise deps.GenerationCancelled("台本生成をキャンセルしました。") from error
        raise deps.TransportFailure("connection", "stream" if stream else "response", partial_body=content) from error
    finally:
        if not final:
            deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason = "missing_terminal_event"
        _native_diagnostics(debug_response_path, content, raw_events, final, payload, sanitizer)
        if connection is not None:
            deps.close_openai_http_post(connection)


def ollama_native_json_result(
    request: Any, *, system: str, user: dict[str, Any], max_tokens: int, allow_plain_draft: bool,
    return_content: bool, debug_response_path: Path | None, should_cancel: Callable[[], bool] | None,
    job_id: str | None, sampling: dict[str, Any], benchmark_seed: int | None = None,
) -> dict[str, Any] | str:
    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    if debug_response_path is not None:
        deps.write_draft_debug_request(
            debug_response_path, request=request, system=system, user=user, max_tokens=max_tokens, sampling=sampling
        )
    content = ""
    usage: int | None = None
    try:
        content, usage = ollama_native_completion(
            request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, stream=False,
            should_cancel=should_cancel, job_id=job_id,
            benchmark_seed=benchmark_seed, debug_response_path=debug_response_path, prepared=True,
        )
    finally:
        metrics = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None)
        deps.record_draft_llm_usage(job_id, metrics if isinstance(metrics, dict) else usage, input_estimate=deps.estimate_llm_input_tokens(system, user),
                                    output_text=content, provider=request.provider, model=request.model)
        deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    if return_content:
        return content
    try:
        return deps.extract_draft_response(content) if allow_plain_draft else deps.extract_json(content)
    except HTTPException as error:
        raise RuntimeError(str(error.detail)) from error


def ollama_native_stream_result(
    request: Any, *, system: str, user: dict[str, Any], max_tokens: int, debug_response_path: Path | None,
    on_progress: Callable[[str], None] | None, loop_detector: Callable[[str], str | None] | None,
    should_cancel: Callable[[], bool] | None, job_id: str | None, sampling: dict[str, Any],
    benchmark_seed: int | None = None,
) -> str:
    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    if debug_response_path is not None:
        deps.write_draft_debug_request(
            debug_response_path, request=request, system=system, user=user, max_tokens=max_tokens, sampling=sampling
        )
    content = ""
    usage: int | None = None
    try:
        content, usage = ollama_native_completion(
            request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, stream=True,
            on_progress=on_progress, loop_detector=loop_detector, should_cancel=should_cancel, job_id=job_id,
            benchmark_seed=benchmark_seed, debug_response_path=debug_response_path, prepared=True,
        )
    finally:
        metrics = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None)
        deps.record_draft_llm_usage(job_id, metrics if isinstance(metrics, dict) else usage, input_estimate=deps.estimate_llm_input_tokens(system, user),
                                    output_text=content, provider=request.provider, model=request.model)
        deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    if on_progress:
        on_progress(content)
    if not content.strip():
        raise RuntimeError("Ollama native API は本文を返しませんでした。")
    return content


deps.register(__name__, [
    "NATIVE_FLAG", "OllamaContentSanitizer", "ollama_native_completion", "ollama_native_enabled", "ollama_structured_enabled", "ollama_native_json_result",
    "ollama_native_stream_result",
])

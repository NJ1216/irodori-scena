"""Translate SCENA's OpenAI-shaped chat traffic to the Anthropic Messages API.

Only the official https://api.anthropic.com endpoint is translated. Feature code
keeps one OpenAI-shaped request/response boundary; this module rewrites the wire
format (headers, body, response and SSE events) at the HTTP seam.
"""
from __future__ import annotations

import json
import re
from typing import Any, Iterator
from urllib.parse import quote, urlsplit

ANTHROPIC_HOST = "api.anthropic.com"
ANTHROPIC_VERSION = "2026-10-21"
_ROOT_PATHS = {"", "/v1"}
_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
           "model_context_window_exceeded": "length",
           "refusal": "content_filter", "tool_use": "tool_calls", "pause_turn": "stop"}
_EFFORT = {"none": "low", "minimal": "low", "low": "low", "medium": "medium",
           "high": "high", "xhigh": "xhigh", "max": "max"}
# The Messages API rejects these JSON Schema constraints; SCENA validates records itself.
_UNSUPPORTED_SCHEMA_KEYS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                            "minLength", "maxLength", "minItems", "maxItems", "uniqueItems"}


def _official_path(url: str, suffixes: tuple[str, ...] = ()) -> str | None:
    try:
        parsed = urlsplit(str(url or "").strip())
    except (TypeError, ValueError):
        return None
    if (parsed.scheme != "https" or parsed.hostname != ANTHROPIC_HOST or parsed.port not in {None, 443}
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        return None
    path = parsed.path.rstrip("/")
    for suffix in suffixes:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return path if path in _ROOT_PATHS else None


def is_anthropic_base_url(base_url: str) -> bool:
    return _official_path(base_url, ("/chat/completions", "/messages", "/models")) is not None


def anthropic_chat_endpoint(endpoint: str) -> bool:
    return (_official_path(endpoint, ("/chat/completions",)) is not None
            and str(endpoint).rstrip("/").endswith("/chat/completions"))


def anthropic_models_url(after_id: str | None = None) -> str:
    url = f"https://{ANTHROPIC_HOST}/v1/models?limit=1000"
    return f"{url}&after_id={quote(after_id, safe='')}" if after_id else url


def anthropic_headers(headers: dict[str, str]) -> dict[str, str]:
    """Move an OpenAI-style bearer key to Anthropic's x-api-key header."""
    result = {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION}
    authorization = next((value for key, value in headers.items() if key.lower() == "authorization"), "")
    if authorization.startswith("Bearer ") and authorization[7:].strip():
        result["x-api-key"] = authorization[7:].strip()
    return result


def effort_supported(model: str) -> bool:
    identity = model.strip().lower()
    if identity.startswith(("claude-fable", "claude-mythos")):
        return True
    match = re.match(r"claude-(opus|sonnet|haiku)-(\d+)(?:-(\d+))?", identity)
    if not match:
        return False
    family, major, minor = match.group(1), int(match.group(2)), int(match.group(3) or 0)
    if major >= 5:
        return True
    if major != 4 or minor >= 100:  # dated IDs such as claude-sonnet-4-20250514
        return False
    return minor >= (5 if family == "opus" else 6) if family in {"opus", "sonnet"} else False


def _schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ({name: _schema(item) for name, item in nested.items()}
                      if key in {"properties", "$defs", "definitions"} and isinstance(nested, dict) else _schema(nested))
                for key, nested in value.items() if key not in _UNSUPPORTED_SCHEMA_KEYS}
    if isinstance(value, list):
        return [_schema(item) for item in value]
    return value


def messages_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a Messages request; sampling, seed and OpenAI-only options are not sent."""
    system: list[str] = []
    messages: list[dict[str, str]] = []
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if message.get("role") in {"system", "developer"}:
            system.append(text)
        else:
            messages.append({"role": "assistant" if message.get("role") == "assistant" else "user", "content": text})
    model = str(payload.get("model") or "")
    body: dict[str, Any] = {
        "model": model,
        "max_tokens": payload.get("max_tokens") or payload.get("max_completion_tokens") or 4096,
        "messages": messages,
    }
    if system:
        body["system"] = "\n\n".join(system)
    if payload.get("stream"):
        body["stream"] = True
    output_config: dict[str, Any] = {}
    effort = _EFFORT.get(str(payload.get("reasoning_effort") or ""))
    if effort and effort_supported(model):
        output_config["effort"] = effort
    response_format = payload.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
        schema = (response_format.get("json_schema") or {}).get("schema")
        if isinstance(schema, dict):
            output_config["format"] = {"type": "json_schema", "schema": _schema(schema)}
    if output_config:
        body["output_config"] = output_config
    return body


def outgoing_request(endpoint: str, body: bytes, headers: dict[str, str]) -> tuple[str, bytes, dict[str, str], bool | None]:
    """Return the request to send; the flag is None for non-Anthropic traffic, else the stream mode."""
    if not anthropic_chat_endpoint(endpoint):
        return endpoint, body, headers, None
    payload = json.loads(body.decode("utf-8"))
    translated = messages_payload(payload if isinstance(payload, dict) else {})
    return (f"https://{ANTHROPIC_HOST}/v1/messages", json.dumps(translated, ensure_ascii=False).encode("utf-8"),
            anthropic_headers(headers), bool(translated.get("stream")))


def _usage(input_usage: dict[str, Any], output_tokens: Any) -> dict[str, Any]:
    def number(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    cached = number(input_usage.get("cache_read_input_tokens"))
    prompt = number(input_usage.get("input_tokens")) + cached + number(input_usage.get("cache_creation_input_tokens"))
    completion = number(output_tokens)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
            "prompt_tokens_details": {"cached_tokens": cached}}


def _refusal(message: dict[str, Any]) -> str:
    details = message.get("stop_details") if isinstance(message.get("stop_details"), dict) else {}
    return str(details.get("explanation") or "refusal")


def openai_completion(message: dict[str, Any]) -> dict[str, Any]:
    blocks = message.get("content") if isinstance(message.get("content"), list) else []
    text = "".join(str(block.get("text") or "") for block in blocks
                   if isinstance(block, dict) and block.get("type") == "text")
    stop = message.get("stop_reason")
    reply: dict[str, Any] = {"role": "assistant", "content": text}
    if stop == "refusal":
        reply["refusal"] = _refusal(message)
    usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    return {"id": message.get("id"), "model": message.get("model"),
            "choices": [{"index": 0, "message": reply, "finish_reason": _FINISH.get(str(stop), "stop")}],
            "usage": _usage(usage, usage.get("output_tokens"))}


class AnthropicStreamError(ConnectionError):
    """A transient provider error event inside a stream; partial text handling stays with the reader."""


class AnthropicStreamRejected(RuntimeError):
    """A non-transient error event inside a stream; never resent."""


_TRANSIENT_STREAM_ERRORS = {"overloaded_error", "api_error", "rate_limit_error", "timeout_error"}


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


class _StreamTranslator:
    def __init__(self) -> None:
        self.input_usage: dict[str, Any] = {}

    def feed(self, line: str) -> Iterator[str]:
        line = line.strip()
        if not line.startswith("data:"):
            return
        try:
            event = json.loads(line[5:].strip())
        except ValueError:
            return
        event = _object(event)
        kind = event.get("type")
        if kind == "message_start":
            self.input_usage = _object(_object(event.get("message")).get("usage"))
        elif kind == "content_block_delta":
            delta = _object(event.get("delta"))
            if delta.get("type") == "text_delta" and delta.get("text"):
                yield _chunk({"content": str(delta["text"])}, None)
        elif kind == "message_delta":
            stop = _object(event.get("delta")).get("stop_reason")
            delta = {"refusal": _refusal(_object(event.get("delta")))} if stop == "refusal" else {}
            usage = _object(event.get("usage"))
            yield _chunk(delta, _FINISH.get(str(stop), "stop") if stop else None,
                         _usage(self.input_usage, usage.get("output_tokens")))
        elif kind == "message_stop":
            yield "data: [DONE]"
        elif kind == "error":
            error_type = str(_object(event.get("error")).get("type") or "unknown")
            failure = AnthropicStreamError if error_type in _TRANSIENT_STREAM_ERRORS else AnthropicStreamRejected
            raise failure(f"Anthropic stream error: {error_type}")


def _chunk(delta: dict[str, Any], finish: str | None, usage: dict[str, Any] | None = None) -> str:
    event: dict[str, Any] = {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
    if usage is not None:
        event["usage"] = usage
    return "data: " + json.dumps(event, ensure_ascii=False)


class MessagesResponse:
    """Present an Anthropic HTTP response as an OpenAI chat-completions response."""

    def __init__(self, raw: Any, *, stream: bool) -> None:
        self._raw = raw
        self._stream = stream
        status = int(getattr(raw, "status", 200))
        self.status = 503 if status == 529 else status  # 529 overloaded joins the retryable 503 path
        self.headers = getattr(raw, "headers", {})

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)

    def read(self, *args: Any) -> bytes:
        if self.status >= 400:
            return self._raw.read(*args)
        if self._stream:
            return b"".join(line + b"\n" for line in self)
        return json.dumps(openai_completion(json.loads(self._raw.read().decode("utf-8"))),
                          ensure_ascii=False).encode("utf-8")

    def __iter__(self) -> Iterator[bytes]:
        if self.status >= 400 or not self._stream:
            yield from self._raw
            return
        translator = _StreamTranslator()
        for raw_line in self._raw:
            text = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else str(raw_line)
            translated = list(translator.feed(text))
            # An empty line per ping/thinking event keeps the reader's per-line cancellation check running.
            yield from (line.encode("utf-8") for line in translated) if translated else (b"",)


def model_ids(payload: Any) -> tuple[list[str], str | None]:
    """Return model IDs and the next page cursor of one Models API page."""
    items = payload.get("data") if isinstance(payload, dict) else None
    ids = [str(item.get("id")).strip() for item in items or [] if isinstance(item, dict) and item.get("id")]
    after = payload.get("last_id") if isinstance(payload, dict) and payload.get("has_more") else None
    return ids, str(after) if after else None

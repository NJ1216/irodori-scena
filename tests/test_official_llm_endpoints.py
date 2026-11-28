from __future__ import annotations

import scena_test_isolation  # noqa: F401
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import server.app  # noqa: F401
from server.modules import (anthropic_messages, common, llm_catalog, llm_client, llm_official_endpoints,
                            llm_probe_response, llm_sampling, llm_transport)

ANTHROPIC = "https://api.anthropic.com/v1"
OPENAI = "https://api.openai.com/v1"


def _request(base_url: str, model: str, api_key: str = "sk-test") -> SimpleNamespace:
    return SimpleNamespace(provider="openai", base_url=base_url, model=model, api_key=api_key)


def _sse(*events: dict) -> list[bytes]:
    lines: list[bytes] = []
    for event in events:
        lines += [f"event: {event['type']}\n".encode(), f"data: {json.dumps(event)}\n".encode(), b"\n"]
    return lines


class _Raw:
    def __init__(self, status: int, body: bytes = b"", lines: list[bytes] | None = None,
                 content_type: str = "application/json") -> None:
        self.status = status
        self.headers = {"content-type": content_type}
        self._body = body
        self._lines = lines or []

    def read(self, *_args):
        return self._body

    def __iter__(self):
        return iter(self._lines)


class AnthropicPayloadTests(unittest.TestCase):
    def test_messages_payload_moves_system_and_drops_openai_only_options(self) -> None:
        payload = {"model": "claude-opus-5-5", "max_tokens": 900, "stream": True, "temperature": 0.7,
                   "top_p": 0.9, "seed": 3, "stream_options": {"include_usage": True}, "reasoning_effort": "none",
                   "messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "{\"a\":1}"}]}
        body = anthropic_messages.messages_payload(payload)
        self.assertEqual(body, {"model": "claude-opus-5-5", "max_tokens": 900, "system": "rules", "stream": True,
                                "messages": [{"role": "user", "content": "{\"a\":1}"}],
                                "output_config": {"effort": "low"}})

    def test_effort_is_omitted_for_models_that_reject_it(self) -> None:
        for model in ("claude-haiku-4-5", "claude-sonnet-4-5-20250929", "claude-sonnet-4-20250514"):
            with self.subTest(model=model):
                body = anthropic_messages.messages_payload(
                    {"model": model, "max_tokens": 10, "reasoning_effort": "low", "messages": []})
                self.assertNotIn("output_config", body)
        for model in ("claude-sonnet-5-5", "claude-fable-5-2", "claude-opus-4-6", "claude-sonnet-4-6"):
            self.assertTrue(anthropic_messages.effort_supported(model), model)

    def test_json_schema_becomes_output_format_without_unsupported_constraints(self) -> None:
        schema = {"type": "object", "additionalProperties": False, "required": ["records"], "properties": {
            "records": {"type": "array", "minItems": 1, "items": {"anyOf": [
                {"type": "integer", "minimum": 0, "maximum": 9}, {"type": "string", "maxLength": 4}]}}}}
        body = anthropic_messages.messages_payload({"model": "claude-haiku-4-5", "max_tokens": 10, "messages": [],
            "response_format": {"type": "json_schema", "json_schema": {"name": "x", "strict": True, "schema": schema}}})
        records = body["output_config"]["format"]["schema"]["properties"]["records"]
        self.assertEqual(body["output_config"]["format"]["type"], "json_schema")
        self.assertNotIn("minItems", records)
        self.assertEqual(records["items"]["anyOf"], [{"type": "integer"}, {"type": "string"}])

    def test_schema_constraints_are_stripped_but_property_names_are_kept(self) -> None:
        schema = {"type": "object", "properties": {"minimum": {"type": "integer", "minimum": 1}},
                  "required": ["minimum"], "additionalProperties": False}
        self.assertEqual(anthropic_messages._schema(schema)["properties"], {"minimum": {"type": "integer"}})

    def test_only_the_official_https_endpoint_is_translated(self) -> None:
        body = json.dumps({"model": "m", "messages": []}).encode()
        headers = {"Content-Type": "application/json", "Authorization": "Bearer key"}
        for endpoint in ("http://api.anthropic.com/v1/chat/completions", "https://proxy.example/v1/chat/completions",
                         "https://api.anthropic.com/v1/models", "https://api.anthropic.com/v2/chat/completions"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(anthropic_messages.outgoing_request(endpoint, body, headers),
                                 (endpoint, body, headers, None))
        target, sent, sent_headers, stream = anthropic_messages.outgoing_request(
            "https://api.anthropic.com/chat/completions", body, headers)
        self.assertEqual(target, "https://api.anthropic.com/v1/messages")
        self.assertEqual(sent_headers, {"Content-Type": "application/json", "anthropic-version": "2026-10-21",
                                        "x-api-key": "key"})
        self.assertFalse(stream)
        self.assertEqual(json.loads(sent)["max_tokens"], 4096)


class AnthropicTransportTests(unittest.TestCase):
    def _post(self, raw: _Raw, payload: dict):
        connection = MagicMock()
        connection.getresponse.return_value = raw
        with patch.object(common.http.client, "HTTPSConnection", return_value=connection) as factory:
            _, response = common.openai_http_post(f"{ANTHROPIC}/chat/completions",
                                                  body=json.dumps(payload).encode(),
                                                  headers={"Authorization": "Bearer sk-test"})
        factory.assert_called_once()
        self.assertEqual(factory.call_args.args[0], "api.anthropic.com")
        method, path = connection.request.call_args.args
        sent_headers = connection.request.call_args.kwargs["headers"]
        self.assertEqual((method, path), ("POST", "/v1/messages"))
        self.assertEqual(sent_headers["x-api-key"], "sk-test")
        self.assertNotIn("Authorization", sent_headers)
        return response

    def test_nonstream_response_is_returned_as_a_chat_completion(self) -> None:
        message = {"id": "msg_1", "model": "claude-opus-5-5", "stop_reason": "max_tokens", "content": [
            {"type": "thinking", "thinking": ""}, {"type": "text", "text": "本文"}],
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 7}}
        response = self._post(_Raw(200, json.dumps(message).encode()), {"model": "claude-opus-5-5", "messages": []})
        converted = json.loads(response.read())
        self.assertEqual(converted["choices"][0]["message"]["content"], "本文")
        self.assertEqual(converted["choices"][0]["finish_reason"], "length")
        self.assertEqual(llm_client.extract_usage_metrics(converted),
                         {"promptTokens": 15, "completionTokens": 7, "cachedTokens": 5, "totalTokens": 22})

    def test_overloaded_529_joins_the_retryable_503_path_and_keeps_the_error_body(self) -> None:
        response = self._post(_Raw(529, b'{"type":"error"}'), {"model": "claude-opus-5-5", "messages": []})
        self.assertEqual(response.status, 503)
        self.assertEqual(response.read(), b'{"type":"error"}')

    def test_stream_events_become_openai_chunks_with_usage(self) -> None:
        lines = _sse(
            {"type": "message_start", "message": {"usage": {"input_tokens": 12, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "x"}},
            {"type": "ping"},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "A|こん"}},
            {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "にちは"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 30}},
            {"type": "message_stop"},
        ) + [b"data: must-not-be-read\n"]
        response = self._post(_Raw(200, lines=lines, content_type="text/event-stream"),
                              {"model": "claude-opus-5-5", "stream": True, "messages": []})
        content, total = llm_client._stream_response_content(
            response, on_progress=None, loop_detector=None, should_cancel=None)
        self.assertEqual(content, "A|こんにちは")
        self.assertEqual(total, 42)
        self.assertEqual(llm_client.deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason, "stop")

    def test_stream_error_after_text_preserves_partial_body_without_resend(self) -> None:
        lines = _sse({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "usable"}},
                     {"type": "error", "error": {"type": "overloaded_error", "message": "secret"}})
        response = anthropic_messages.MessagesResponse(_Raw(200, lines=lines), stream=True)
        with self.assertRaises(llm_transport.TransportFailure) as raised:
            llm_client._stream_response_content(response, on_progress=None, loop_detector=None, should_cancel=None)
        self.assertEqual(raised.exception.partial_body, "usable")
        self.assertFalse(llm_transport.is_retryable(raised.exception, received_body=True))

    def test_non_transient_stream_error_is_not_retryable_and_pings_keep_cancellation_checks(self) -> None:
        lines = _sse({"type": "ping"}, {"type": "error", "error": {"type": "invalid_request_error"}})
        response = anthropic_messages.MessagesResponse(_Raw(200, lines=lines), stream=True)
        checks = []
        with self.assertRaises(anthropic_messages.AnthropicStreamRejected) as raised:
            list(llm_client.deps.openai_stream_data(response, lambda: checks.append(1) and False))
        self.assertFalse(llm_transport.is_retryable(raised.exception))
        self.assertGreaterEqual(len(checks), 3)
        transient = anthropic_messages.MessagesResponse(_Raw(200, lines=_sse(
            {"type": "error", "error": {"type": "overloaded_error"}})), stream=True)
        with self.assertRaises(anthropic_messages.AnthropicStreamError) as overloaded:
            list(transient)
        self.assertTrue(llm_transport.is_retryable(overloaded.exception))

    def test_refusal_is_reported_as_refusal_not_text(self) -> None:
        lines = _sse({"type": "message_delta", "delta": {"stop_reason": "refusal",
                      "stop_details": {"type": "refusal", "explanation": "declined"}}, "usage": {"output_tokens": 0}},
                     {"type": "message_stop"})
        response = anthropic_messages.MessagesResponse(_Raw(200, lines=lines), stream=True)
        content, _ = llm_client._stream_response_content(response, on_progress=None, loop_detector=None,
                                                          should_cancel=None)
        self.assertEqual(content, "")
        self.assertEqual(llm_client.deps.DRAFT_LLM_THREAD_CONTEXT.refusal, "declined")
        self.assertEqual(llm_client.deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason, "content_filter")

    def test_model_list_uses_x_api_key_and_follows_pages(self) -> None:
        pages = [{"data": [{"id": "claude-sonnet-5-5"}], "has_more": True, "last_id": "claude-sonnet-5-5"},
                 {"data": [{"id": "claude-opus-5-5"}, {"id": "claude-sonnet-5-5"}], "has_more": False}]
        calls = []

        def urlopen(call, timeout):
            calls.append(call)
            return io.BytesIO(json.dumps(pages[len(calls) - 1]).encode())

        request = SimpleNamespace(provider="openai", base_url=ANTHROPIC, api_key="sk-test")
        with patch.object(llm_client.urllib.request, "urlopen", side_effect=urlopen):
            self.assertEqual(llm_client.list_llm_models(request), ["claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertEqual(calls[0].full_url, "https://api.anthropic.com/v1/models?limit=1000")
        self.assertTrue(calls[1].full_url.endswith("&after_id=claude-sonnet-5-5"))
        self.assertEqual(calls[0].get_header("X-api-key"), "sk-test")
        self.assertIsNone(calls[0].get_header("Authorization"))

    def test_sampling_and_probe_budget_follow_the_official_endpoint(self) -> None:
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value={"temperature": 0.4, "topP": 0.8}):
            self.assertEqual(llm_sampling.resolve_sampling_settings(_request(ANTHROPIC, "claude-opus-5-5"), 0.7), {})
            self.assertEqual(llm_sampling.resolve_sampling_settings(_request(OPENAI, "gpt-4.1"), 0.7),
                             {"temperature": 0.4, "top_p": 0.8})
        for base_url in (ANTHROPIC, OPENAI):
            selected = {"provider": "openai", "model": "m", "baseUrl": base_url}
            self.assertEqual(llm_probe_response.probe_options(selected, 64), {"max_tokens": 4096})
        self.assertEqual(llm_probe_response.probe_options(
            {"provider": "openai", "model": "m", "baseUrl": "https://proxy.example/v1"}, 64), {"max_tokens": 64})

    def test_anthropic_defaults_to_low_effort_unless_thinking_is_enabled(self) -> None:
        for thinking, expected in ((False, "low"), (True, None)):
            with patch("server.modules.llm_registry.resolve_llm_settings", return_value={"thinking": thinking}):
                payload = llm_official_endpoints.prepare_official_payload(
                    _request(ANTHROPIC, "claude-opus-5-5"), {"model": "claude-opus-5-5", "max_tokens": 5})
            self.assertEqual(payload.get("reasoning_effort"), expected)

    def test_catalog_fills_claude_limits_for_the_official_endpoint_only(self) -> None:
        result = llm_catalog.effective_capabilities("openai", ANTHROPIC, "claude-sonnet-5-5", {})
        self.assertEqual((result["inputTokenLimit"], result["outputTokenLimit"]), (1000000, 128000))
        self.assertEqual(result["catalog"]["verifiedAt"], "2026-11-28")
        self.assertNotIn("inputTokenLimit",
                         llm_catalog.effective_capabilities("openai", "https://proxy.example/v1", "claude-sonnet-5-5", {}))


class OpenAiOfficialTests(unittest.TestCase):
    def setUp(self) -> None:
        llm_official_endpoints._REJECTED.clear()

    def test_official_openai_uses_max_completion_tokens(self) -> None:
        payload = llm_official_endpoints.prepare_official_payload(
            _request(OPENAI, "gpt-5.2"), {"model": "gpt-5.2", "max_tokens": 50, "temperature": 0.7})
        self.assertEqual(payload, {"model": "gpt-5.2", "max_completion_tokens": 50, "temperature": 0.7})
        other = llm_official_endpoints.prepare_official_payload(
            _request("https://proxy.example/v1", "m"), {"model": "m", "max_tokens": 50})
        self.assertEqual(other, {"model": "m", "max_tokens": 50})

    def test_rejected_sampling_value_is_dropped_once_and_remembered_for_the_model(self) -> None:
        request = _request(OPENAI, "gpt-5")
        detail = json.dumps({"error": {"param": "temperature", "code": "unsupported_value", "message": "x"}})
        first = 400, detail.encode()
        responses = [Mock(status=status, headers={}, read=Mock(return_value=body)) for status, body in (
            first, (200, b'{"choices":[{"message":{"content":"ok"}}]}'))]
        sent = []

        def post(endpoint, body, headers, should_cancel):
            sent.append(json.loads(body))
            return object(), responses[len(sent) - 1]

        with (patch("server.modules.common.openai_http_post", side_effect=post),
              patch("server.modules.common.close_openai_http_post"),
              patch.object(llm_transport, "before_attempt")):
            result = llm_transport.openai_nonstream_payload(
                request, f"{OPENAI}/chat/completions", {"model": "gpt-5", "max_tokens": 9, "temperature": 0.7}, None)
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        self.assertEqual(sent[0]["temperature"], 0.7)
        self.assertNotIn("temperature", sent[1])
        later = llm_official_endpoints.prepare_official_payload(request, {"model": "gpt-5", "temperature": 0.7})
        self.assertNotIn("temperature", later)
        self.assertEqual(llm_official_endpoints.prepare_official_payload(request, {"temperature": 1}),
                         {"temperature": 1})
        self.assertIn("temperature", llm_official_endpoints.prepare_official_payload(
            _request(OPENAI, "gpt-4.1"), {"model": "gpt-4.1", "temperature": 1}))

    def test_a_rejected_value_does_not_block_other_values_of_the_same_parameter(self) -> None:
        request = _request(OPENAI, "gpt-6")
        detail = json.dumps({"error": {"param": "reasoning_effort", "code": "unsupported_value"}})
        payload = {"reasoning_effort": "none"}
        self.assertTrue(llm_official_endpoints.adapt_rejected_parameter(request, payload, 400, detail))
        self.assertEqual(payload, {})
        self.assertEqual(llm_official_endpoints.prepare_official_payload(request, {"reasoning_effort": "none"}), {})
        self.assertEqual(llm_official_endpoints.prepare_official_payload(request, {"reasoning_effort": "high"}),
                         {"reasoning_effort": "high"})

    def test_only_named_droppable_parameters_are_adapted(self) -> None:
        request = _request("https://proxy.example/v1", "m")
        payload = {"max_tokens": 5, "response_format": {}, "messages": []}
        reject = lambda param, code="unsupported_parameter": json.dumps(  # noqa: E731
            {"error": {"param": param, "code": code}})
        self.assertFalse(llm_official_endpoints.adapt_rejected_parameter(request, payload, 400, reject("messages")))
        self.assertFalse(llm_official_endpoints.adapt_rejected_parameter(request, payload, 400,
                                                                         reject("response_format")))
        self.assertFalse(llm_official_endpoints.adapt_rejected_parameter(request, payload, 400,
                                                                         reject("max_tokens", "invalid_value")))
        self.assertFalse(llm_official_endpoints.adapt_rejected_parameter(request, payload, 500, reject("max_tokens")))
        self.assertFalse(llm_official_endpoints.adapt_rejected_parameter(request, payload, 400, "not json"))
        self.assertTrue(llm_official_endpoints.adapt_rejected_parameter(request, payload, 400, reject("max_tokens")))
        self.assertEqual(payload, {"max_completion_tokens": 5, "response_format": {}, "messages": []})
        ollama = SimpleNamespace(provider="ollama", base_url="http://127.0.0.1:11434/v1", model="m")
        self.assertFalse(llm_official_endpoints.adapt_rejected_parameter(
            ollama, {"temperature": 1}, 400, reject("temperature")))

    def test_official_model_list_hides_non_chat_models(self) -> None:
        ids = ["gpt-5.2", "text-embedding-3-large", "tts-1", "whisper-1", "gpt-image-1", "gpt-4.1"]
        self.assertEqual(llm_official_endpoints.chat_model_ids(OPENAI, ids), ["gpt-5.2", "gpt-4.1"])
        self.assertEqual(llm_official_endpoints.chat_model_ids("https://proxy.example/v1", ids), ids)


if __name__ == "__main__":
    unittest.main()

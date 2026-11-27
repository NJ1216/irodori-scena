from __future__ import annotations

import scena_test_isolation  # noqa: F401
import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from server.modules import common, llm_client, llm_registry, llm_stream_transport, llm_transport, runtime_state
from server.modules.llm_gemini_options import prepare_gemini_payload
from server.modules.llm_retry_budget import DraftRetryBudget


class GeminiGenerationTests(unittest.TestCase):
    def setUp(self):
        self.request = SimpleNamespace(provider="openai", model="models/gemini-3.5-flash", api_key="fixture-key",
                                       base_url="https://generativelanguage.googleapis.com/v1beta/openai")
        self.payload = {"model": self.request.model, "stream": True, "max_tokens": 3925,
                        "messages": [{"role": "user", "content": "自己紹介"}], "temperature": 0.8}
        settings = patch.object(llm_registry, "resolve_llm_settings", return_value={"thinking": False})
        self.settings = settings.start()
        self.addCleanup(settings.stop)
        context = patch.object(runtime_state, "DRAFT_LLM_THREAD_CONTEXT", SimpleNamespace())
        context.start()
        self.addCleanup(context.stop)

    def response(self, status, payload):
        response = io.BytesIO(json.dumps(payload).encode())
        response.status = status
        response.headers = {"content-type": "application/json"}
        return response

    def stream(self, *, reader=None, cancel=None):
        return llm_stream_transport.openai_stream_response(
            self.request, endpoint=self.request.base_url + "/chat/completions", payload=self.payload,
            debug_response_path=None, on_progress=None, loop_detector=None, should_cancel=cancel,
            read_response=reader or llm_client._read_text_completion_response,
        )

    def test_default_thinking_off_matches_probe_without_changing_budget_or_original(self):
        result = prepare_gemini_payload(self.request, self.payload)
        self.assertEqual(result["reasoning_effort"], "low")
        self.assertEqual(result["max_tokens"], 3925)
        self.assertNotIn("reasoning_effort", self.payload)
        self.assertEqual(result["messages"], self.payload["messages"])

    def test_explicit_thinking_and_non_google_endpoints_are_not_overridden(self):
        self.settings.return_value = {"thinking": True}
        self.assertEqual(prepare_gemini_payload(self.request, self.payload), self.payload)
        self.settings.return_value = {"thinking": False}
        explicit = {**self.payload, "reasoning_effort": "high"}
        self.assertEqual(prepare_gemini_payload(self.request, explicit), explicit)
        for url in ("http://localhost/v1", "https://generativelanguage.googleapis.com.evil.test/v1beta/openai",
                    "https://generativelanguage.googleapis.com/custom", "https://api.openai.com/v1"):
            self.request.base_url = url
            self.assertEqual(prepare_gemini_payload(self.request, self.payload), self.payload)

    def test_normal_and_schema_nonstream_calls_share_the_low_setting(self):
        for extra in ({}, {"response_format": {"type": "json_schema", "json_schema": {"name": "fixture"}}}):
            payload = {**self.payload, **extra, "stream": False}
            response = self.response(200, {"choices": [{"message": {"content": "usable"}}]})
            with patch.object(common, "openai_http_post", return_value=(Mock(), response)) as post:
                result = llm_transport.openai_nonstream_payload(self.request, self.request.base_url, payload, None)
            sent = json.loads(post.call_args.kwargs["body"])
            self.assertEqual(sent, {**payload, "reasoning_effort": "low"})
            self.assertEqual(result["choices"][0]["message"]["content"], "usable")

    def test_stream_503_falls_back_to_same_request_and_preserves_content_finish_and_usage(self):
        good = {"choices": [{"message": {"content": "NORMAL|A|自己紹介です"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 4126, "completion_tokens": 2177, "total_tokens": 6829}}
        first, second = Mock(), Mock()
        with patch.object(common, "openai_http_post", side_effect=[
            (first, self.response(503, {"error": {"status": "UNAVAILABLE"}})),
            (second, self.response(200, good)),
        ]) as post, patch.object(llm_transport, "cancellable_wait"):
            content, usage = self.stream()
        sent = [json.loads(call.kwargs["body"]) for call in post.call_args_list]
        self.assertTrue(sent[0]["stream"])
        self.assertFalse(sent[1]["stream"])
        self.assertNotIn("stream_options", sent[1])
        for payload in sent:
            self.assertEqual(payload["reasoning_effort"], "low")
            for key in ("model", "messages", "temperature", "max_tokens"):
                self.assertEqual(payload[key], self.payload[key])
        self.assertEqual(content, "NORMAL|A|自己紹介です")
        self.assertEqual(usage, 6829)
        self.assertEqual(runtime_state.DRAFT_LLM_THREAD_CONTEXT.finish_reason, "stop")
        first.close.assert_called_once()
        second.close.assert_called_once()

    def test_partial_body_and_cancellation_are_never_replayed(self):
        for error in (llm_transport.TransportFailure("overloaded", "stream", status=503, partial_body="usable"),
                      common.GenerationCancelled("cancel")):
            with patch.object(common, "openai_http_post", return_value=(Mock(), self.response(200, {}))) as post, \
                 patch.object(llm_transport, "cancellable_wait") as wait:
                with self.assertRaises(type(error)) as raised:
                    self.stream(reader=Mock(side_effect=error))
            self.assertIs(raised.exception, error)
            post.assert_called_once()
            wait.assert_not_called()

    def test_job_retries_are_shared_and_nonstream_is_retained_for_next_call(self):
        runtime_state.DRAFT_LLM_THREAD_CONTEXT.retry_budget = DraftRetryBudget()
        good = {"choices": [{"message": {"content": "NORMAL|A|こんにちは。"}, "finish_reason": "stop"}]}
        responses = [(Mock(), self.response(status, good if status == 200 else {}))
                     for status in (503, 200, 503, 503)]
        with patch.object(common, "openai_http_post", side_effect=responses) as post, \
             patch.object(llm_transport, "cancellable_wait"):
            self.assertIn("こんにちは", self.stream()[0])
            with self.assertRaises(llm_transport.TransportFailure):
                self.stream()
            with self.assertRaises(llm_transport.TransportFailure):
                self.stream()
        self.assertEqual(post.call_count, 4)
        self.assertEqual([json.loads(call.kwargs["body"])["stream"] for call in post.call_args_list],
                         [True, False, False, False])

    def test_fallback_uses_existing_four_attempt_limit(self):
        with patch.object(common, "openai_http_post", side_effect=lambda *args, **kwargs: (
            Mock(), self.response(503, {"error": {"status": "UNAVAILABLE"}})
        )) as post, patch.object(llm_transport, "cancellable_wait") as wait:
            with self.assertRaises(llm_transport.TransportFailure):
                self.stream()
        self.assertEqual(post.call_count, 4)
        self.assertEqual(wait.call_count, 3)
        self.assertEqual([json.loads(call.kwargs["body"])["stream"] for call in post.call_args_list],
                         [True, False, False, False])

    def test_rate_limit_and_other_providers_do_not_switch_transport(self):
        for status, url in ((429, self.request.base_url), (503, "https://example.test/v1")):
            self.request.base_url = url
            with patch.object(common, "openai_http_post", side_effect=lambda *args, **kwargs: (
                Mock(), self.response(status, {})
            )) as post, patch.object(llm_transport, "cancellable_wait"):
                with self.assertRaises(llm_transport.TransportFailure):
                    self.stream()
            self.assertTrue(all(json.loads(call.kwargs["body"])["stream"] for call in post.call_args_list))

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import io
import json
import threading
import unittest
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import llm_model_tests
from server.modules.llm_probe_response import ProbeResponseError, probe_completion_text, probe_options


class GeminiModelProbeTests(unittest.TestCase):
    def test_all_gemini_probe_requests_allow_thinking_and_visible_output(self) -> None:
        selected = {"provider": "openai", "model": "gemini-3.5-flash", "apiKey": "test-key",
                    "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai"}
        content = json.dumps({"records": [{"choice": "A"}]})
        for mode in ("completion", "schema_nonstream", "schema_stream"):
            with self.subTest(mode=mode):
                if mode == "schema_stream":
                    events = [{"choices": []}, {"choices": [{"delta": {"content": content}}]}]
                    raw = "".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n"
                else:
                    raw = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})
                with patch.object(llm_model_tests.urllib.request, "urlopen", return_value=io.BytesIO(raw.encode())) as opening:
                    if mode == "completion":
                        self.assertEqual(llm_model_tests._completion(selected, threading.Event()), content)
                    else:
                        result = llm_model_tests._schema_probe(selected, threading.Event(), stream=mode == "schema_stream")
                        self.assertEqual(result["state"], "schema_validated")
                opening.assert_called_once()
                request = opening.call_args.args[0]
                payload = json.loads(request.data)
                self.assertEqual(request.full_url, selected["baseUrl"] + "/chat/completions")
                self.assertEqual(payload["max_tokens"], 4096)
                self.assertEqual(payload["reasoning_effort"], "low")

    def test_other_models_keep_their_probe_settings(self) -> None:
        for provider, model in (("ollama", "gemma4"), ("lmstudio", "model"), ("scena-local", "model"),
                                ("openai", "other-model"), ("openai", "gemini-2.0-flash")):
            self.assertEqual(probe_options({"provider": provider, "model": model}, 80), {"max_tokens": 80})

    def test_empty_truncated_blocked_and_malformed_responses_are_distinct(self) -> None:
        cases = [
            ({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}, "output_limit"),
            ({"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}, "empty_response"),
            ({"choices": [{"message": {"refusal": "refused"}}]}, "response_blocked"),
            ({"choices": []}, "invalid_response"),
            ({"choices": [None]}, "invalid_response"),
            ({"choices": [{"message": None}]}, "invalid_response"),
        ]
        for payload, category in cases:
            with self.subTest(category=category):
                with self.assertRaises(ProbeResponseError) as raised:
                    probe_completion_text(payload)
                self.assertEqual(llm_model_tests._failure_category(raised.exception), category)

    def test_usable_text_survives_output_limit_without_retry(self) -> None:
        payload = {"choices": [{"message": {"content": "接続確認済み"}, "finish_reason": "length"}]}
        self.assertEqual(probe_completion_text(payload), "接続確認済み")

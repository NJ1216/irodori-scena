from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import unittest
from unittest.mock import patch

from server.app import DraftRequest, build_draft_capability_profile, list_llm_models, openai_json_completion, openai_stream_text_completion
from server.registry import deps


def request() -> DraftRequest:
    return DraftRequest(
        provider="lmstudio",
        base_url="http://127.0.0.1:1234/v1",
        model="loaded-llm",
        character_ids=["cast-a"],
        target_minutes=2,
        theme="雨の日に二人が小さな約束をする十分な長さのテーマです。",
    )


class LmStudioNativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handoff = patch("server.modules.windows_external_memory._is_windows_local", return_value=False)
        self.handoff.start()
        self.addCleanup(self.handoff.stop)

    def tearDown(self) -> None:
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None

    def test_model_list_uses_native_endpoint_and_only_returns_llms(self) -> None:
        payload = {
            "data": [
                {"id": "loaded-llm", "type": "llm"},
                {"id": "embedding", "type": "embedding"},
            ]
        }
        with patch("server.modules.lmstudio_native._native_json_request", return_value=payload) as native:
            self.assertEqual(list_llm_models(request()), ["loaded-llm"])
        self.assertEqual(native.call_args.args[0], "http://127.0.0.1:1234/api/v1/models")

    def test_128_gib_profile_caps_context_to_native_model_and_loaded_instance(self) -> None:
        model_payload = {
            "data": [{
                "id": "loaded-llm", "type": "llm", "max_context_length": 65536,
                "loaded_instances": [{"config": {"context_length": 32768}}],
            }]
        }
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=128),
            patch("server.modules.lmstudio_native._native_json_request", return_value=model_payload),
        ):
            profile = build_draft_capability_profile(request())
        self.assertEqual(profile["contextCeiling"], 32768)
        self.assertEqual(profile["effectiveContext"], 8192)
        self.assertEqual(profile["modelContextLimit"], 65536)
        self.assertEqual(profile["runningContext"], 32768)
        self.assertLess(profile["maxChunkCharacters"], 5000)
        self.assertEqual(profile["predictedCalls"], 1)

    def test_native_json_request_maps_fields_and_extracts_message_content(self) -> None:
        class Response:
            status = 200
            headers: dict[str, str] = {}

            def read(self) -> bytes:
                return json.dumps({"output": [{"message": {"content": '{"answer":"ok"}'}}], "stats": {"input_tokens": 12, "total_output_tokens": 8}}).encode()

        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = {"provider": "lmstudio", "effectiveContext": 32768}
        sampling = {"temperature": 0.35, "topP": 0.9, "topK": 40, "minP": 0.05, "repetitionPenalty": 1.1}
        with (patch("server.modules.common.openai_http_post", return_value=(object(), Response())) as post,
              patch("server.modules.llm_registry.resolve_llm_settings", return_value=sampling)):
            result = openai_json_completion(request(), system="system", user={"question": "test"}, max_tokens=900)
        self.assertEqual(result, {"answer": "ok"})
        self.assertEqual(post.call_args.args[0], "http://127.0.0.1:1234/api/v1/chat")
        payload = json.loads(post.call_args.kwargs["body"])
        self.assertEqual(payload["system_prompt"], "system")
        self.assertEqual(json.loads(payload["input"]), {"question": "test"})
        self.assertEqual(payload["context_length"], 32768)
        self.assertEqual(payload["max_output_tokens"], 900)
        self.assertIs(payload["store"], False)
        self.assertNotIn("previous_response_id", payload)
        self.assertEqual((payload["temperature"], payload["top_p"], payload["top_k"]), (0.35, 0.9, 40))
        self.assertEqual((payload["min_p"], payload["repeat_penalty"]), (0.05, 1.1))
        self.assertNotIn("messages", payload)

    def test_native_stream_collects_only_message_delta_and_final_usage(self) -> None:
        class Response:
            status = 200
            headers = {"content-type": "text/event-stream"}

            def __iter__(self):
                yield b"event: reasoning.delta\n"
                yield b'data: {"content":"ignore"}\n'
                yield b"event: message.delta\n"
                yield b'data: {"content":"hello"}\n'
                yield b"event: message.delta\n"
                yield b'data: {"content":" world"}\n'
                yield b"event: chat.end\n"
                yield b'data: {"result":{"stats":{"input_tokens":11,"total_output_tokens":7}}}\n'

        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = {"provider": "lmstudio", "effectiveContext": 32768}
        job_id = "lmstudio-native-usage"
        deps.DRAFT_JOBS[job_id] = {"id": job_id, "usedTokens": 0, "tokenUsageAvailable": True}
        try:
            with patch("server.modules.common.openai_http_post", return_value=(object(), Response())) as post:
                self.assertEqual(openai_stream_text_completion(request(), system="system", user={}, max_tokens=100, job_id=job_id), "hello world")
            payload = json.loads(post.call_args.kwargs["body"])
            self.assertIs(payload["stream"], True)
            self.assertIs(payload["store"], False)
            self.assertNotIn("previous_response_id", payload)
            self.assertEqual(deps.DRAFT_JOBS[job_id]["usedTokens"], 18)
        finally:
            deps.DRAFT_JOBS.pop(job_id, None)

    def test_native_api_missing_does_not_retry_openai_compatible_endpoint(self) -> None:
        class Response:
            status = 404
            headers: dict[str, str] = {}

            def read(self) -> bytes:
                return b"not found"

        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = {"provider": "lmstudio", "effectiveContext": 4096}
        with patch("server.modules.common.openai_http_post", return_value=(object(), Response())) as post:
            with self.assertRaisesRegex(RuntimeError, "LM Studio native v1 API が必要"):
                openai_json_completion(request(), system="system", user={}, max_tokens=100)
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith("/api/v1/chat"))

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from server.app import DRAFT_JOBS, DraftRequest, GenerationCancelled, openai_json_completion, openai_stream_text_completion
from server.modules.ollama_native import NATIVE_FLAG, OllamaContentSanitizer, ollama_native_enabled
from server.registry import deps


def request() -> DraftRequest:
    return DraftRequest(
        provider="ollama", base_url="http://127.0.0.1:11434/v1", model="test-model",
        character_ids=["cast-a"], target_minutes=1, theme="十分な長さのテストテーマです。",
    )


class OllamaNativeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handoff = patch("server.modules.windows_external_memory._is_windows_local", return_value=False)
        self.handoff.start()
        self.addCleanup(self.handoff.stop)
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = {
            "provider": "ollama", "contextCeiling": 8192, "effectiveContext": 8192, "jobContext": 8192,
        }

    def tearDown(self) -> None:
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None

    def test_sanitizer_fixture_matrix_preserves_usable_content_at_every_wrapper_boundary(self) -> None:
        fixed = [
            (["短い返事です。"], "短い返事です。"),
            (["A|一行目\n", "B|二行目"], "A|一行目\nB|二行目"),
            (["A|有効\nB|途", "中"], "A|有効\nB|途中"),
            (["<think>破損"], ""),
            (["前", "<THINK mode=\"x\">秘密</think   >", "後"], "前後"),
            (["L1|direction=静かに\n", "L2|rate=1.1"], "L1|direction=静かに\nL2|rate=1.1"),
            (["長文" * 4000], "長文" * 4000),
            (["😊有効な兄弟", "<think>🚫</think>", "B|保持"], "😊有効な兄弟B|保持"),
        ]
        wrapper = '<think kind="analysis">hidden</think>visible'
        cases = [*fixed, *[([wrapper[:split], wrapper[split:]], "visible") for split in range(1, len(wrapper))]]
        self.assertGreaterEqual(len(cases), 30)
        for chunks, expected in cases:
            sanitizer = OllamaContentSanitizer()
            snapshots: list[str] = []
            accepted = ""
            for chunk in chunks:
                accepted += sanitizer.feed(chunk)
                snapshots.append(accepted)
            accepted += sanitizer.finish()
            self.assertEqual(accepted, expected)
            self.assertFalse(any("<thi" in snapshot.casefold() for snapshot in snapshots))

    def test_sanitizer_never_exposes_any_split_control_token_prefix(self) -> None:
        token = "<|arbitrary-control|>"
        for split in range(1, len(token)):
            sanitizer = OllamaContentSanitizer()
            accepted = sanitizer.feed("前" + token[:split])
            self.assertNotIn("<|", accepted)
            accepted += sanitizer.feed(token[split:] + "後") + sanitizer.finish()
            self.assertEqual(accepted, "前後")

    def test_gemma_thought_channel_keeps_siblings_without_publishing_reasoning(self) -> None:
        wrappers = ["前<|channel>thought\n秘密<channel|>後<|turn>",
                    "前<|channel|>analysis\n秘密<|channel|>final\n後"]
        for wrapper in wrappers:
            for split in range(len(wrapper) + 1):
                sanitizer = OllamaContentSanitizer()
                first = sanitizer.feed(wrapper[:split])
                self.assertNotIn("秘密", first)
                self.assertEqual(first + sanitizer.feed(wrapper[split:]) + sanitizer.finish(), "前後")
        sanitizer = OllamaContentSanitizer()
        self.assertEqual(sanitizer.feed("前<|channel>thought\n切れた秘密") + sanitizer.finish(), "前")

    def test_sanitizer_preserves_ordinary_angle_text_and_short_eof_prefixes_verbatim(self) -> None:
        values = ["<", "<t", "<th", "<thi", "<thin", "<thinker>", "</thinker>", "<tag>本文</tag>"]
        for value in values:
            for split in range(len(value) + 1):
                sanitizer = OllamaContentSanitizer()
                accepted = sanitizer.feed(value[:split]) + sanitizer.feed(value[split:]) + sanitizer.finish()
                self.assertEqual(accepted, value, (value, split))

    def test_sanitizer_discards_truncated_prohibited_material_without_publishing_a_prefix(self) -> None:
        values = ["<think", "<think ", "<think mode=analysis", "</think", "</think   ", "<|", "<|control"]
        for value in values:
            for split in range(len(value) + 1):
                sanitizer = OllamaContentSanitizer()
                snapshots = [sanitizer.feed(value[:split]), sanitizer.feed(value[split:])]
                self.assertEqual(snapshots, ["", ""], (value, split))
                self.assertEqual(sanitizer.finish(), "")

    def test_transport_is_off_by_default_and_requires_ollama_identity(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(NATIVE_FLAG, None)
            self.assertFalse(ollama_native_enabled(request()))
        other = request().model_copy(update={"provider": "openai"})
        with patch.dict(os.environ, {NATIVE_FLAG: "1"}):
            self.assertFalse(ollama_native_enabled(other))

    def test_non_stream_uses_native_chat_without_leaking_reasoning_and_records_metrics(self) -> None:
        class Response:
            status = 200
            headers: dict[str, str] = {}

            def read(self) -> bytes:
                return json.dumps({
                    "message": {"content": '<think>hidden</think>{"answer":"ok"}', "thinking": "secret"},
                    "done": True, "prompt_eval_count": 12, "eval_count": 8,
                    "prompt_eval_duration": 2_000_000_000, "eval_duration": 1_000_000_000,
                    "load_duration": 500_000_000, "total_duration": 4_000_000_000,
                }).encode()

        job_id = "ollama-native-json"
        DRAFT_JOBS[job_id] = {"id": job_id, "usedTokens": 0, "tokenUsageAvailable": True}
        try:
            with (
                patch.dict(os.environ, {NATIVE_FLAG: "1"}),
                patch("server.modules.llm_registry.resolve_llm_settings", return_value={
                    "ttlSeconds": 600, "temperature": 0.2, "topP": 0.8, "topK": 20,
                }),
                patch("server.modules.common.openai_http_post", return_value=(object(), Response())) as post,
            ):
                result = openai_json_completion(
                    request(), system="system", user={"question": "test"}, max_tokens=90, job_id=job_id
                )
            self.assertEqual(result, {"answer": "ok"})
            self.assertEqual(post.call_args.args[0], "http://127.0.0.1:11434/api/chat")
            payload = json.loads(post.call_args.kwargs["body"])
            self.assertEqual((payload["think"], payload["keep_alive"], payload["stream"]), (False, "600s", False))
            self.assertEqual(payload["options"]["num_predict"], 90)
            self.assertEqual(
                (payload["options"]["temperature"], payload["options"]["top_p"], payload["options"]["top_k"]),
                (0.2, 0.8, 20),
            )
            self.assertEqual(DRAFT_JOBS[job_id]["usedTokens"], 20)
            self.assertEqual(DRAFT_JOBS[job_id]["ollamaNativeMetrics"]["tokensPerSecond"], 8.0)
            self.assertGreaterEqual(DRAFT_JOBS[job_id]["ollamaNativeMetrics"]["ttftSeconds"], 0)
        finally:
            DRAFT_JOBS.pop(job_id, None)

    def test_stream_keeps_body_before_unfinished_reasoning_without_fallback(self) -> None:
        class Response:
            status = 200
            headers: dict[str, str] = {}

            def __iter__(self):
                yield json.dumps({"message": {"content": "safe"}, "done": False}).encode()
                yield json.dumps({"message": {"content": "<|channel|>analysis"}, "done": False}).encode()

        with (
            patch.dict(os.environ, {NATIVE_FLAG: "1"}),
            patch("server.modules.llm_registry.resolve_llm_settings", return_value={"ttlSeconds": 0}),
            patch("server.modules.common.openai_http_post", return_value=(object(), Response())) as post,
        ):
            result = openai_stream_text_completion(request(), system="system", user={}, max_tokens=20)
        self.assertEqual(result, "safe")
        self.assertEqual(deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason, "missing_terminal_event")
        self.assertEqual(post.call_count, 1)
        self.assertTrue(post.call_args.args[0].endswith("/api/chat"))
        self.assertEqual(json.loads(post.call_args.kwargs["body"])["keep_alive"], 0)

    def test_stream_payload_includes_num_ctx_and_native_metrics(self) -> None:
        class Response:
            status = 200
            headers: dict[str, str] = {}

            def __iter__(self):
                yield json.dumps({"message": {"content": "ok"}, "done": False}).encode()
                yield json.dumps({
                    "message": {"content": ""}, "done": True, "prompt_eval_count": 4, "eval_count": 2,
                    "prompt_eval_duration": 2_000_000_000, "eval_duration": 1_000_000_000,
                }).encode()

        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = {"provider": "ollama", "effectiveContext": 8192}
        job_id = "ollama-native-missing-metrics"
        DRAFT_JOBS[job_id] = {"id": job_id, "usedTokens": 0, "tokenUsageAvailable": True}
        try:
            with (
                patch.dict(os.environ, {NATIVE_FLAG: "1"}),
                patch("server.modules.llm_registry.resolve_llm_settings", return_value={}),
                patch("server.modules.common.openai_http_post", return_value=(object(), Response())) as post,
            ):
                self.assertEqual(openai_stream_text_completion(
                    request(), system="system", user={}, max_tokens=20, job_id=job_id
                ), "ok")
            payload = json.loads(post.call_args.kwargs["body"])
            self.assertEqual(payload["options"]["num_ctx"], 8192)
            self.assertEqual(DRAFT_JOBS[job_id]["usedTokens"], 6)
            self.assertEqual(DRAFT_JOBS[job_id]["ollamaNativeMetrics"]["tokensPerSecond"], 2.0)
        finally:
            DRAFT_JOBS.pop(job_id, None)

    def test_missing_and_malformed_native_metrics_are_unavailable(self) -> None:
        class Response:
            status = 200
            headers: dict[str, str] = {}

            def __init__(self, metrics: dict[str, object]) -> None:
                self.metrics = metrics

            def read(self) -> bytes:
                return json.dumps({"message": {"content": "plain"}, "done": True, **self.metrics}).encode()

        for suffix, metrics in (("missing", {}), ("malformed", {
            "prompt_eval_count": True, "eval_count": -1, "eval_duration": "bad",
        })):
            job_id = f"ollama-native-{suffix}-metrics"
            DRAFT_JOBS[job_id] = {"id": job_id, "usedTokens": 0, "tokenUsageAvailable": True}
            try:
                with (
                    patch.dict(os.environ, {NATIVE_FLAG: "1"}),
                    patch("server.modules.llm_registry.resolve_llm_settings", return_value={}),
                    patch("server.modules.common.openai_http_post", return_value=(object(), Response(metrics))),
                ):
                    self.assertEqual(openai_json_completion(
                        request(), system="system", user={}, max_tokens=20, return_content=True, job_id=job_id
                    ), "plain")
                self.assertFalse(DRAFT_JOBS[job_id]["tokenUsageAvailable"])
                self.assertIsNone(DRAFT_JOBS[job_id]["ollamaNativeMetrics"]["tokensPerSecond"])
            finally:
                DRAFT_JOBS.pop(job_id, None)

    def test_native_http_error_and_malformed_event_do_not_fallback(self) -> None:
        class ErrorResponse:
            status = 500
            headers: dict[str, str] = {}

            def read(self) -> bytes:
                return b"native failed"

        for response, message in ((ErrorResponse(), "不正な応答"),):
            with (
                patch.dict(os.environ, {NATIVE_FLAG: "1"}),
                patch("server.modules.llm_registry.resolve_llm_settings", return_value={}),
                patch("server.modules.common.openai_http_post", return_value=(object(), response)) as post,
                self.assertRaisesRegex(RuntimeError, message),
            ):
                openai_json_completion(request(), system="system", user={}, max_tokens=20)
            self.assertEqual(post.call_count, 1)
            self.assertTrue(post.call_args.args[0].endswith("/api/chat"))

        class MalformedResponse:
            status = 200
            headers: dict[str, str] = {}

            def __iter__(self):
                yield b"not-json"

        with (
            patch.dict(os.environ, {NATIVE_FLAG: "1"}),
            patch("server.modules.llm_registry.resolve_llm_settings", return_value={}),
            patch("server.modules.common.openai_http_post", return_value=(object(), MalformedResponse())) as post,
            self.assertRaisesRegex(RuntimeError, "接続できません"),
        ):
            openai_stream_text_completion(request(), system="system", user={}, max_tokens=20)
        self.assertEqual(post.call_count, 1)

    def test_native_stream_honors_cancellation_before_publishing_content(self) -> None:
        class Response:
            status = 200
            headers: dict[str, str] = {}

            def __iter__(self):
                yield json.dumps({"message": {"content": "do not publish"}, "done": False}).encode()

        with (
            patch.dict(os.environ, {NATIVE_FLAG: "1"}),
            patch("server.modules.llm_registry.resolve_llm_settings", return_value={}),
            patch("server.modules.common.openai_http_post", return_value=(object(), Response())),
            self.assertRaises(GenerationCancelled),
        ):
            openai_stream_text_completion(
                request(), system="system", user={}, max_tokens=20, should_cancel=lambda: True
            )


if __name__ == "__main__":
    unittest.main()

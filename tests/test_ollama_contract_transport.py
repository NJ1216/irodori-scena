import os
import unittest
from unittest.mock import patch

from server.app import (DraftRequest, LlmRecordContract, complete_records, extract_required_sources,
                        required_source_schema, DRAFT_LLM_THREAD_CONTEXT)
from server.modules.ollama_context import load_ollama_allocation, DraftContextError
from server.modules.llm_transport import TransportFailure
from ollama_http_fixture import OllamaServer


def contract():
    properties = {"source": {"type": "string"}, "speaker": {"type": "string", "enum": ["A"]},
                  "text": {"type": "string"}, "direction": {"type": "string"},
                  "source_complete": {"type": "boolean"}}
    return LlmRecordContract("draft-dialogue", 2, {"properties": properties}, "source", frozenset({"D1"}),
        merge_by_owner=False, response_schema_override=required_source_schema(["D1"], {"type": "object"}),
        record_extractor=lambda content: extract_required_sources(content, ["D1"]))


class OllamaContractTransportTests(unittest.TestCase):
    def setUp(self):
        handoff = patch("server.modules.windows_external_memory._is_windows_local", return_value=False)
        settings = patch("server.modules.llm_registry.resolve_llm_settings", return_value={})
        handoff.start()
        settings.start()
        self.addCleanup(handoff.stop)
        self.addCleanup(settings.stop)
        self.addCleanup(lambda: setattr(DRAFT_LLM_THREAD_CONTEXT, "capability_profile", None))
        DRAFT_LLM_THREAD_CONTEXT.capability_profile = {
            "provider": "ollama", "jobContext": 32768, "contextCeiling": 32768, "effectiveContext": 32768}

    def request(self, server):
        return DraftRequest(provider="ollama", base_url=server.base_url, model="fixture",
                            character_ids=["a"], theme="これは検証用です。", target_minutes=1)

    def test_stream_and_nonstream_keep_identical_partial_fields_and_actual_settings(self):
        body = '<think>秘密</think>{"D1":{"lines":[{"speaker":"UNKNOWN","text":"対象外"},' \
               '{"speaker":"A","text":"引用\\\"改行\\n括弧[]😊","direction":"途中'
        for stream, split in ((False, 4096), (True, 1), (True, 71)):
            with self.subTest(stream=stream, split=split), OllamaServer(lambda _p: (body, "length"), split=split) as server:
                progress = []
                result = complete_records(self.request(server), contract=contract(), system="保持の検証", user={},
                    max_tokens=512, stream=stream, benchmark_seed=43, on_records=progress.extend)
                self.assertEqual([(r["speaker"], r["text"]) for r in result.records], [("A", '引用"改行\n括弧[]')])
                self.assertEqual(len(progress), 1)
                self.assertEqual(result.transport.finish_reason, "length")
                self.assertTrue(result.transport.partial)
                self.assertEqual(result.transport.usage["completionTokens"], 100)
                payload = server.requests[-1][1]
                self.assertEqual(payload["options"]["seed"], 43)
                self.assertEqual(payload["options"]["num_predict"], 512)

    def test_missing_terminal_event_is_not_normal_completion(self):
        body = '{"D1":{"lines":[{"speaker":"A","text":"終わりです。"}],"complete":true}}'
        with OllamaServer(lambda _p: (body, None)) as server:
            result = complete_records(self.request(server), contract=contract(), system="検証", user={},
                                      max_tokens=512, stream=True)
        self.assertEqual(len(result.records), 1)
        self.assertEqual(result.transport.finish_reason, "missing_terminal_event")
        self.assertTrue(result.transport.partial)

    def test_control_tokens_do_not_discard_valid_sibling_records(self):
        body = ('<|channel>thought\n秘密<channel|>{"D1":{"lines":['
                '{"speaker":"A","text":"前"},<|arbitrary-control|>'
                '{"speaker":"A","text":"後"}],"complete":true}}')
        for stream in (False, True):
            with self.subTest(stream=stream), OllamaServer(lambda _p: (body, "stop"), split=1) as server:
                progress = []
                result = complete_records(self.request(server), contract=contract(), system="検証", user={},
                                          max_tokens=512, stream=stream, on_records=progress.extend)
            self.assertEqual([r["text"] for r in result.records], ["前", "後"])
            self.assertEqual([r["text"] for r in progress], ["前", "後"])
            self.assertEqual(result.transport.finish_reason, "stop")

    def test_unknown_sibling_fields_do_not_abort_publication(self):
        body = '{"D1":{"lines":[{"speaker":"UNKNOWN","text":"不明"},{"speaker":"A","text":"保持","mystery":42}]}}'
        with OllamaServer(lambda _p: (body, "stop")) as server:
            result = complete_records(self.request(server), contract=contract(), system="検証", user={},
                                      max_tokens=512, stream=True)
        self.assertEqual(result.records[0]["text"], "保持")
        self.assertNotIn("mystery", result.records[0])
        self.assertTrue(any(item.get("reason") == "unknown_field" for item in result.manifest))

    def test_load_cancellation_sends_no_creative_request(self):
        with OllamaServer(lambda _p: ("", "stop")) as server:
            from server.app import GenerationCancelled
            with self.assertRaises(GenerationCancelled):
                load_ollama_allocation(self.request(server), should_cancel=lambda: True)
            self.assertEqual(server.requests, [])

    def test_context_failure_precedes_http(self):
        DRAFT_LLM_THREAD_CONTEXT.capability_profile.update(jobContext=4096, contextCeiling=4096)
        with OllamaServer(lambda _p: ("", "stop")) as server:
            with self.assertRaises(DraftContextError):
                complete_records(self.request(server), contract=contract(), system="長文" * 5000,
                                 user={}, max_tokens=512, stream=True)
            self.assertEqual(server.requests, [])

    def test_transport_exception_survives_context_manager_traceback(self):
        from contextlib import contextmanager
        @contextmanager
        def boundary():
            yield
        with self.assertRaises(TransportFailure):
            with boundary():
                raise TransportFailure("connection", "stream", partial_body="保持")

    def test_plain_job_uses_same_native_seed_context_budget_and_terminal_reason(self):
        from server.app import openai_json_completion, openai_stream_text_completion
        from server.modules.ollama_native import NATIVE_FLAG
        self.addCleanup(lambda: setattr(DRAFT_LLM_THREAD_CONTEXT, "job_id", None))
        DRAFT_LLM_THREAD_CONTEXT.job_id = "plain-http-contract"
        for stream in (False, True):
            with self.subTest(stream=stream), patch.dict(os.environ, {NATIVE_FLAG: "0"}), \
                 OllamaServer(lambda _p: ('{"answer":"保持"}', "length")) as server:
                method = openai_stream_text_completion if stream else openai_json_completion
                options = {} if stream else {"return_content": True}
                text = method(self.request(server), system="検証", user={}, max_tokens=512,
                              benchmark_seed=44, **options)
                self.assertIn("保持", text)
                path, payload = server.requests[-1]
                self.assertEqual(path, "/api/chat")
                self.assertNotIn("format", payload)
                self.assertEqual(payload["options"]["seed"], 44)
                self.assertEqual(payload["options"]["num_ctx"], 32768)
                self.assertEqual(payload["options"]["num_predict"], 512)
                self.assertEqual(DRAFT_LLM_THREAD_CONTEXT.finish_reason, "length")

    def test_pinned_job_oom_requires_replanning_without_reducing_context(self):
        from server.app import reduce_ollama_context
        profile = DRAFT_LLM_THREAD_CONTEXT.capability_profile
        self.assertFalse(reduce_ollama_context(profile, "out of memory allocating context"))
        self.assertEqual(profile["effectiveContext"], 32768)
        self.assertTrue(profile["contextReplanRequired"])

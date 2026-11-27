from __future__ import annotations

import scena_test_isolation  # noqa: F401
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from server.draft_protocol import parse_plan_protocol
from server.registry import deps
from server.modules import common, draft_capability, llm_client, llm_stream_transport, runtime_state


PLAN = """TITLE: 放課後の自己紹介
STORY: 友人同士が互いを紹介する。
CAST_CONTEXT:
A: 彩は快活な学生。
B: 葵は穏やかな学生。
CHAPTER 1:
目的: 互いの好きなことを知る。
開始状態: 教室で話し始める。
展開:
・好きな食べ物を紹介する。
・最近の趣味を紹介する。
・次の予定を相談する。
終了状態: 一緒に帰る。
新規性: 二人の好みが分かる。
継続条件: 呼び方を維持する。"""


class OllamaCloudDraftTests(unittest.TestCase):
    def test_aggregate_json_plan_keeps_partial_chapters_and_developments(self):
        content = json.dumps({
            "script_title": "雨宿りの約束", "story_bible": "雨宿りをきっかけに二人が本音を話す。",
            "chapters": [
                {"chapter_index": 1, "chapter_title": "軒下の再会", "purpose": "雨を避ける",
                 "developments": ["偶然再会する", "傘がないと分かる"],
                 "start_state": "一人で立っている", "end_state": "二人で話し始める"},
                {"chapter_index": 2, "purpose": "本音を伝える", "developments": ["誤解を解く"],
                 "start_state": "距離がある", "end_state": "一緒に帰る"},
            ],
        }, ensure_ascii=False)
        records, partial = deps.draft_plan_contract(set()).record_extractor(content)
        plan = deps.plan_from_records(tuple(records))
        self.assertFalse(partial)
        self.assertEqual(plan["title"], "雨宿りの約束")
        self.assertEqual([chapter["beats"] for chapter in plan["chapters"]],
                         [["偶然再会する", "傘がないと分かる"], ["誤解を解く"]])
        self.assertEqual(plan["chapters"][1]["closing_state"], "一緒に帰る")

    def test_truncated_aggregate_json_keeps_closed_chapter_and_valid_siblings(self):
        content = ('{"chapters":[{"chapter_index":1,"purpose":"再会する",'
                   '"developments":["声をかける"],"start_state":"離れている"},'
                   '{"chapter_index":2,"purpose":"途中')
        records, partial = deps.draft_plan_contract(set()).record_extractor(content)
        plan = deps.plan_from_records(tuple(records))
        self.assertTrue(partial)
        self.assertEqual(len(plan["chapters"]), 1)
        self.assertEqual(plan["chapters"][0]["beats"], ["声をかける"])
        self.assertEqual(plan["chapters"][0]["opening_state"], "離れている")

    def test_missing_aggregate_chapter_title_uses_phase_not_internal_input_name(self):
        response = json.dumps({"title": "生成題", "chapters": [
            {"chapter_index": 1, "purpose": "出会う", "developments": ["声をかける"]},
        ]}, ensure_ascii=False)
        request = deps.DraftRequest(character_ids=["a"], target_minutes=3, theme="見出しのない作者入力")
        with tempfile.TemporaryDirectory() as directory, \
             patch("server.modules.llm_completion_service._schema_enabled", return_value=False), \
             patch("server.modules.llm_client.openai_text_completion", return_value=response):
            plan = deps.create_draft_plan(request, cast_context=[{"cast": "A", "name": "彩"}],
                chunk_count=1, target_characters=800, token_budget=2048, debug_directory=Path(directory))
        self.assertEqual(plan["chapters"][0]["title"], "第1部：導入")
        self.assertNotIn("入力", plan["chapters"][0]["title"])

    def test_fallback_title_keeps_explicit_author_heading(self):
        request = deps.DraftRequest(character_ids=["a"], target_minutes=3,
                                    theme="# 雨の再会\n軒下で再会する。")
        self.assertEqual(deps.fallback_story_chapters(request, 1)[0]["title"], "雨の再会")

    def test_cloud_request_does_not_receive_local_num_ctx_option(self):
        request = SimpleNamespace(provider="ollama", model="gemma4:31b-cloud", api_key="",
                                  base_url="http://fixture.invalid/v1")
        payload = {"messages": [], "max_tokens": 1024}
        context = SimpleNamespace(capability_profile={"effectiveContext": 32768})
        with patch.object(runtime_state, "DRAFT_LLM_THREAD_CONTEXT", context):
            draft_capability.apply_ollama_context(payload, request)
        self.assertNotIn("options", payload)

    def test_readable_plan_variants_keep_chapter_casts_and_verbatim_fields(self):
        plan = parse_plan_protocol(PLAN)
        self.assertEqual(len(plan["chapters"]), 1)
        self.assertEqual(plan["cast_contexts"]["A"], {"role": "", "description": "彩は快活な学生。"})
        chapter = plan["chapters"][0]
        self.assertEqual(chapter["objective"], "互いの好きなことを知る。")
        self.assertEqual(chapter["beats"], ["好きな食べ物を紹介する。", "最近の趣味を紹介する。", "次の予定を相談する。"])
        self.assertEqual(chapter["closing_state"], "一緒に帰る。")
        self.assertEqual(chapter["novelty_requirement"], "二人の好みが分かる。")

    def test_partial_plan_keeps_valid_siblings_without_inventing_missing_fields(self):
        plan = parse_plan_protocol("CAST_CONTEXT:\nA: 彩の紹介。\nB:\nCHAPTER 1:\n目的: 自己紹介\n展開:\n・挨拶する。\n終了状態:")
        self.assertEqual(set(plan["cast_contexts"]), {"A"})
        self.assertEqual(plan["chapters"][0]["beats"], ["挨拶する。"])
        self.assertEqual(plan["chapters"][0]["closing_state"], "")
        outside = parse_plan_protocol("A: 所属不明の文章。\nCHAPTER|1|通常\nOBJECTIVE|目的")
        self.assertEqual(outside["cast_contexts"], {})

    def test_planning_does_not_fallback_or_regenerate_for_observed_variant(self):
        request = deps.DraftRequest(character_ids=["a", "b"], target_minutes=3, theme="自己紹介")
        with tempfile.TemporaryDirectory() as directory, \
             patch("server.modules.llm_completion_service._schema_enabled", return_value=False), \
             patch("server.modules.llm_client.openai_text_completion", return_value=PLAN) as llm:
            plan = deps.create_draft_plan(request, cast_context=[{"cast": "A", "name": "彩"}, {"cast": "B", "name": "葵"}],
                chunk_count=1, target_characters=1123, token_budget=2048, debug_directory=Path(directory))
        self.assertFalse(plan["_planning_fallback_used"])
        self.assertEqual(len(plan["cast_contexts"]), 2)
        self.assertEqual(len(plan["chapters"][0]["beats"]), 3)
        llm.assert_called_once()

    def test_ollama_stream_requests_and_retains_usage_with_unsupported_fallback(self):
        request = SimpleNamespace(provider="ollama", model="gemma4:31b-cloud", api_key="",
                                  base_url="http://fixture.invalid/v1")
        for unsupported in (False, True):
            with self.subTest(unsupported=unsupported):
                payloads = []

                def post(_endpoint, *, body, **_kwargs):
                    payloads.append(json.loads(body))
                    rejected = unsupported and len(payloads) == 1
                    if rejected:
                        response = io.BytesIO(b'{"error":"unsupported stream_options"}')
                    else:
                        response = io.BytesIO(b'data: {"choices":[{"delta":{"content":"usable"},"finish_reason":"stop"}]}\n\n'
                            b'data: {"choices":[],"usage":{"prompt_tokens":100,"completion_tokens":20,"total_tokens":120}}\n\n'
                            b'data: [DONE]\n\n')
                    response.status = 400 if rejected else 200
                    response.headers = {"content-type": "text/event-stream"}
                    return Mock(), response

                context = SimpleNamespace()
                with patch.object(common, "openai_http_post", side_effect=post), \
                     patch.object(runtime_state, "DRAFT_LLM_THREAD_CONTEXT", context):
                    content, total = llm_stream_transport.openai_stream_response(request,
                        endpoint=request.base_url + "/chat/completions",
                        payload={"stream": True, "max_tokens": 100}, debug_response_path=None,
                        on_progress=None, loop_detector=None, should_cancel=None,
                        read_response=llm_client._read_text_completion_response)
                self.assertEqual(content, "usable")
                self.assertEqual(total, 120)
                self.assertEqual(context.provider_usage["promptTokens"], 100)
                self.assertEqual(payloads[0]["stream_options"], {"include_usage": True})
                self.assertEqual(len(payloads), 2 if unsupported else 1)
                if unsupported:
                    self.assertNotIn("stream_options", payloads[1])

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from fastapi import HTTPException
from pydantic import ValidationError

from server.app import (
    DRAFT_JOBS,
    DRAFT_JOBS_LOCK,
    DraftRequest,
    LineAssistantRequest,
    ThemeSuggestionRequest,
    GenerationCancelled,
    draft_cast_alias,
    draft_cast_context,
    cancel_draft_job,
    ensure_draft_not_cancelled,
    openai_text_completion,
    openai_stream_text_completion,
    parse_generated_lines,
    suggest_theme_completion,
)
from server.modules.assistant_routes import line_assistant_completion
class DraftSuggestionsAndStreamTests(unittest.TestCase):
    def test_line_assistant_recovers_a_numeric_continuation_and_strips_direction_emojis(self) -> None:
        response = (
            "LINE|ぼく、お昼寝するの、だーいすきだよ。|"
            "ゆっくりとした、おっとりとしたトーンで、優しく語りかける。😊\n"
            "|1.25|0.7|NONE"
        )

        parsed = parse_generated_lines(response)

        self.assertEqual(
            parsed,
            [
                {
                    "text": "ぼく、お昼寝するの、だーいすきだよ。",
                    "stage_direction": "ゆっくりとした、おっとりとしたトーンで、優しく語りかける。",
                    "speech_rate": 1.25,
                    "gap_seconds": 0.7,
                    "emoji_annotations": [],
                }
            ],
        )

    def test_line_assistant_discards_non_vocal_tail_annotations(self) -> None:
        parsed = parse_generated_lines("LINE|こんにちは！|明るく挨拶する|1.2|0.7|😊@start;😊@end")

        self.assertEqual(
            parsed,
            [
                {
                    "text": "こんにちは！",
                    "stage_direction": "明るく挨拶する",
                    "speech_rate": 1.2,
                    "gap_seconds": 0.7,
                    "emoji_annotations": [{"emoji": "😊", "placement": "line_start"}],
                }
            ],
        )

    def test_line_assistant_passes_a_debug_path_for_generated_lines(self) -> None:
        request = LineAssistantRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            scene_id="scene-a",
            character_id="cast-a",
            instruction="一言追加する",
        )
        project = {
            "characters": [{"id": "cast-a", "name": "彩", "profile": "穏やか"}],
            "scenes": [{"id": "scene-a", "lines": []}],
        }
        captured: dict[str, object] = {}

        def completion(*_args, **kwargs):
            captured.update(kwargs)
            return "LINE|はい。|うなずく|1.2|0.7|NONE"

        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/line-assistant")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
        ):
            result = line_assistant_completion(request, refine_only=False)

        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(captured["debug_response_path"], Path("/tmp/line-assistant/attempt-1.txt"))
        self.assertIn("指定された行数ちょうど", captured["system"])
        self.assertIn("LINE|本文||emoji=NONE|rate=1.00|gap=0.70|direction=穏やかに|cue=NONE", captured["system"])
        self.assertIn("旧 `LINE|本文|ト書き|話速|間|表情注釈` も受理", captured["system"])
    def test_common_speech_rate_requests_accept_engine_bounds(self) -> None:
        draft = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="共通話速の下限を確認するテストテーマです。",
            speech_rate=0.5,
        )
        assistant = LineAssistantRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            scene_id="scene-a",
            character_id="cast-a",
            instruction="間に一言追加する",
            speech_rate=2.0,
        )
        self.assertEqual((draft.speech_rate, assistant.speech_rate), (0.5, 2.0))
        with self.assertRaises(ValidationError):
            DraftRequest(
                base_url="http://127.0.0.1:9999/v1",
                model="test-model",
                character_ids=["cast-a"],
                target_minutes=1,
                theme="範囲外を確認するテストテーマです。",
                speech_rate=2.01,
            )

    def test_theme_suggestion_preserves_source_conditions_and_requests_paragraph(self) -> None:
        request = ThemeSuggestionRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            theme="雨の駅で、幼なじみが再会する。",
            cast_settings={
                "cast-a": {"emoji_expressions": True, "filler_richness": True, "appearance_priority": "main"}
            },
        )
        response = "梅雨の夕方、駅の改札前で幼なじみが再会する。落とし物をきっかけに昔の行き違いと向き合い、次の晴れの日に会う約束を交わす。"
        captured: dict[str, object] = {}

        def completion(*_args, **kwargs):
            captured.update(kwargs)
            return response

        project = {"characters": [{
            "id": "cast-a", "name": "彩", "profile": "慎重だが親しい相手には素直",
            "profileDetails": {"relationships": "幼なじみ", "castRelations": {}},
        }]}
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
        ):
            theme = suggest_theme_completion(request, benchmark_seed=42)
        self.assertEqual(theme, response)
        selected_cast = captured["user"]["selected_cast"]  # type: ignore[index]
        self.assertEqual(selected_cast[0]["name"], "彩")  # type: ignore[index]
        self.assertTrue(selected_cast[0]["draft_settings"]["emoji_expressions"])  # type: ignore[index]
        self.assertIn("固有名詞、人数、場所・時代", captured["system"])
        self.assertIn("250〜350文字", captured["system"])
        self.assertIn("列挙・反復しない", captured["system"])
        self.assertEqual((captured["temperature"], captured["benchmark_seed"]), (0.35, 42))

    def test_theme_suggestion_uses_cast_fitting_mode_for_blank_or_whitespace_source(self) -> None:
        response = "休日の午後、小さな喫茶店で同じ本を手に取ったことから話が始まり、急ぐ事情を知った二人が次の約束を交わす。"
        captured: dict[str, object] = {}

        def completion(*_args, **kwargs):
            captured.update(kwargs)
            return response

        request = ThemeSuggestionRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            theme="  \n\t ",
        )
        project = {"characters": [{"id": "cast-a", "name": "彩", "profileDetails": {}}]}
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch(
                "server.modules.llm_client.openai_text_completion",
                side_effect=completion,
            ),
        ):
            theme = suggest_theme_completion(request)
        user = captured["user"]
        self.assertEqual(user["proposal_mode"], "キャストに合う新規案")  # type: ignore[index]
        self.assertEqual(user["source_theme"], "（指定なし。選択キャストに合う新規案を作る）")  # type: ignore[index]
        self.assertIn("キャスト情報を本文に列挙せず", user["editing_rule"])  # type: ignore[index]
        self.assertEqual(captured["temperature"], 0.8)
        self.assertEqual(theme, response)

    def test_theme_suggestion_recovers_json_fence_once(self) -> None:
        response = """```json
{"theme": "- 時間 ： 夜\\n* 場所：学校の屋上\\n- 参加キャスト ： 選択した二人\\n* キャスト設定の反映：設定を会話へ反映する\\n- シチュエーション：放課後の相談\\n* 導入のきっかけ：呼び出しを受ける\\n- 各者の目的：本音を確かめる\\n* 葛藤・転換：言い出せない事情がある\\n- 感情の流れ：緊張から安堵へ\\n* 結末・余韻：明日の約束を交わす"}
```"""
        request = ThemeSuggestionRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            api_key="do-not-write-this",
            character_ids=["cast-a"],
            theme="学校で話す二人",
        )
        project = {"characters": [{"id": "cast-a", "name": "彩", "profileDetails": {}}]}

        class FakeResponse:
            status = 200
            headers: dict[str, str] = {}

            def __init__(self, content: str) -> None:
                self.content = json.dumps(
                    {"choices": [{"message": {"content": content}}]}, ensure_ascii=False
                ).encode()

            def read(self) -> bytes:
                return self.content

        with (
            TemporaryDirectory() as directory, patch("server.modules.constants.LLM_DEBUG_ENABLED", True),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch(
                "server.modules.workspace.draft_debug_directory",
                return_value=Path(directory),
            ),
            patch(
                "server.modules.common.openai_http_post",
                return_value=(object(), FakeResponse(response)),
            ) as completion,
        ):
            theme = suggest_theme_completion(request)
            self.assertEqual(completion.call_count, 1)
            self.assertIn("時間 ： 夜", theme)
            first_request = (Path(directory) / "attempt-1-request.json").read_text(encoding="utf-8")
            self.assertTrue((Path(directory) / "attempt-1.txt").is_file())
            self.assertFalse((Path(directory) / "attempt-2-request.json").exists())
            self.assertFalse((Path(directory) / "attempt-2.txt").exists())
            self.assertNotIn("http://127.0.0.1:9999/v1", first_request)
            self.assertNotIn("do-not-write-this", first_request)
            payload = json.loads(completion.call_args.kwargs["body"])
            self.assertNotIn("response_format", payload)

    def test_theme_suggestion_accepts_legacy_ten_line_response_as_plain_text(self) -> None:
        response = "\n".join(
            [
                "項目名: 時間, 放課後",
                "項目名: 場所, 学校の屋上",
                "項目名: 参加キャスト, 選択した二人",
                "項目名: キャスト設定の反映, 設定を会話へ反映する",
                "項目名: シチュエーション, 放課後の相談",
                "項目名: 導入のきっかけ, 呼び出しを受ける",
                "項目名: 各者の目的, 本音を確かめる",
                "項目名: 葛藤・転換, 言い出せない事情がある",
                "項目名: 感情の流れ, 緊張から安堵へ",
                "項目名: 結末・余韻, 明日の約束を交わす",
            ]
        )
        request = ThemeSuggestionRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            theme="学校で話す二人",
        )
        project = {"characters": [{"id": "cast-a", "name": "彩", "profileDetails": {}}]}

        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.llm_client.openai_text_completion", return_value=response),
        ):
            theme = suggest_theme_completion(request)

        self.assertEqual(theme, response)

    def test_theme_suggestion_accepts_a_partial_response_without_second_call(self) -> None:
        request = ThemeSuggestionRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            theme="学校で話す二人",
        )
        project = {"characters": [{"id": "cast-a", "name": "彩", "profileDetails": {}}]}
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.llm_client.openai_text_completion", return_value="時間: 夜\n場所: 屋上") as completion,
        ):
            theme = suggest_theme_completion(request)
        self.assertEqual(theme, "時間: 夜\n場所: 屋上")
        self.assertEqual(completion.call_count, 1)

    def test_theme_suggestion_rejects_whitespace_with_specific_error(self) -> None:
        request = ThemeSuggestionRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            theme="学校で話す二人",
        )
        project = {"characters": [{"id": "cast-a", "name": "彩", "profileDetails": {}}]}
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.llm_client.openai_text_completion", return_value=" \n\t "),
            self.assertRaises(HTTPException) as raised,
        ):
            suggest_theme_completion(request)
        self.assertIn("応答が空", raised.exception.detail)

    def test_theme_suggestion_rejects_extremely_short_response(self) -> None:
        request = ThemeSuggestionRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            theme="",
        )
        project = {"characters": [{"id": "cast-a", "name": "彩", "profileDetails": {}}]}
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.llm_client.openai_text_completion", return_value="了解"),
            self.assertRaises(HTTPException) as raised,
        ):
            suggest_theme_completion(request)
        self.assertIn("短すぎ", raised.exception.detail)

    def test_cast_aliases_are_short_and_llm_context_hides_application_ids(self) -> None:
        self.assertEqual((draft_cast_alias(0), draft_cast_alias(25), draft_cast_alias(26)), ("A", "Z", "AA"))
        context = draft_cast_context(
            [{"id": "character_long_internal_id", "name": "Riri", "profileDetails": {}}],
            cast_alias_by_id={"character_long_internal_id": "A"},
        )
        self.assertEqual(context[0]["cast"], "A")
        self.assertNotIn("id", context[0])
        self.assertNotIn("character_long_internal_id", str(context[0]))

    def test_openai_stream_collects_sse_content(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"content-type": "text/event-stream"}

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n'
                yield b'data: {"choices":[{"delta":{"content":" world"}}]}\n'
                yield b"data: [DONE]\n"

        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="十分な長さのテストテーマです。",
        )
        progress: list[str] = []
        with TemporaryDirectory() as directory:
            debug_path = Path(directory) / "response.txt"
            with patch("server.modules.constants.LLM_DEBUG_ENABLED", True), patch("server.modules.common.openai_http_post", return_value=(object(), FakeResponse())):
                content = openai_stream_text_completion(
                    request,
                    system="system",
                    user={"test": True},
                    max_tokens=100,
                    on_progress=progress.append,
                    debug_response_path=debug_path,
                )
            saved_request = json.loads((Path(directory) / "response-request.json").read_text())
            diagnostics = [json.loads(line) for line in (Path(directory) / "response.events.jsonl").read_text().splitlines()]
        self.assertEqual(content, "hello world")
        self.assertEqual(progress[-1], "hello world")
        self.assertEqual(saved_request["system"], "system")
        self.assertEqual(saved_request["sampling"], {"temperature": 0.7})
        self.assertFalse({"base_url", "api_key"} & saved_request.keys())
        self.assertEqual([event["event"] for event in diagnostics], ["request_started", "response_headers_received", "request_finished", "response_completed", "prompt_metrics"])
        self.assertIn("headerWaitSeconds", diagnostics[1])
        self.assertIn("totalSeconds", diagnostics[2])
        self.assertEqual(diagnostics[-2]["receivedCharacters"], len("hello world"))

    def test_draft_job_accumulates_reported_non_stream_usage(self) -> None:
        class FakeResponse:
            status = 200
            headers: dict[str, str] = {}

            def read(self) -> bytes:
                return json.dumps(
                    {"choices": [{"message": {"content": "選別結果"}}], "usage": {"total_tokens": 321}}
                ).encode()

        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model", character_ids=["cast-a"], target_minutes=1, theme="使用量を確認するテーマです。"
        )
        job_id = "draft_job_usage_non_stream"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "usedTokens": 10, "tokenUsageAvailable": True}
        try:
            with patch("server.modules.common.openai_http_post", return_value=(object(), FakeResponse())):
                self.assertEqual(openai_text_completion(request, system="system", user={}, max_tokens=10, job_id=job_id), "選別結果")
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["usedTokens"], 331)
                self.assertTrue(DRAFT_JOBS[job_id]["tokenUsageAvailable"])
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_draft_job_accumulates_final_stream_usage(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"content-type": "text/event-stream"}

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"hello"}}]}\n'
                yield b'data: {"choices":[],"usage":{"total_tokens":456}}\n'
                yield b"data: [DONE]\n"

        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model", character_ids=["cast-a"], target_minutes=1, theme="使用量を確認するテーマです。"
        )
        job_id = "draft_job_usage_stream"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "usedTokens": 0, "tokenUsageAvailable": True}
        try:
            with patch("server.modules.common.openai_http_post", return_value=(object(), FakeResponse())):
                self.assertEqual(openai_stream_text_completion(request, system="system", user={}, max_tokens=10, job_id=job_id), "hello")
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["usedTokens"], 456)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_stream_usage_fallback_marks_the_job_unavailable_without_breaking_generation(self) -> None:
        class RejectedResponse:
            status = 422
            headers: dict[str, str] = {}

            def read(self) -> bytes:
                return b'{"error":"stream_options unsupported"}'

        class FallbackResponse:
            status = 200
            headers = {"content-type": "text/event-stream"}

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"fallback"}}]}\n'
                yield b"data: [DONE]\n"

        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model", provider="openai", character_ids=["cast-a"], target_minutes=1, theme="互換性を確認するテーマです。"
        )
        job_id = "draft_job_usage_fallback"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "usedTokens": 99, "tokenUsageAvailable": True}
        try:
            with patch("server.modules.common.openai_http_post", side_effect=[(object(), RejectedResponse()), (object(), FallbackResponse())]) as post:
                self.assertEqual(openai_stream_text_completion(request, system="system", user={}, max_tokens=10, job_id=job_id), "fallback")
            self.assertEqual(post.call_count, 2)
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["usedTokens"], 99)
                self.assertFalse(DRAFT_JOBS[job_id]["tokenUsageAvailable"])
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_stream_cancellation_stops_at_the_next_received_unit(self) -> None:
        class FakeResponse:
            status = 200
            headers = {"content-type": "text/event-stream"}

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n'
                yield b'data: {"choices":[{"delta":{"content":" second"}}]}\n'

        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="十分な長さのテストテーマです。",
        )
        checks = iter([False, True])
        with patch("server.modules.common.openai_http_post", return_value=(object(), FakeResponse())):
            with self.assertRaises(GenerationCancelled):
                openai_stream_text_completion(
                    request,
                    system="system",
                    user={"test": True},
                    max_tokens=100,
                    should_cancel=lambda: next(checks),
                )

    def test_only_running_draft_job_accepts_cancellation(self) -> None:
        job_id = "draft_job_cancel_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "generating",
                "cancelRequested": False,
            }
        try:
            result = cancel_draft_job(job_id)
            self.assertTrue(result["cancelRequested"])
            with self.assertRaises(GenerationCancelled):
                ensure_draft_not_cancelled(job_id)
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS[job_id]["status"] = "completed"
            with self.assertRaises(HTTPException) as error:
                cancel_draft_job(job_id)
            self.assertEqual(error.exception.status_code, 409)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

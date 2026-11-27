from __future__ import annotations

import scena_test_isolation  # noqa: F401
import itertools
import unittest
from pathlib import Path
from unittest.mock import patch


from server.app import (
    DRAFT_JOBS,
    DRAFT_JOBS_LOCK,
    DRAFT_PROGRESS_CONTEXT,
    DRAFT_PROGRESS_DIALOGUE_START,
    DRAFT_PROGRESS_PLANNING,
    DraftRequest,
    dialogue_output_token_budget,
    create_draft_plan,
    draft_dialogue_simplified_glyphs,
    draft_dialogue_loop_reason,
    draft_dialogue_overall_progress,
    draft_theme_sections,
    draft_performance_loop_reason,
    draft_performance_overall_progress,
    draft_priority_is_satisfied,
    repair_draft_dialogue,
    fixed_dialogue_block_characters,
    first_dialogue_shot_compatibility_message,
    limit_draft_dialogue_characters,
    run_draft_job,
)


class DraftRepairAndJobsTests(unittest.TestCase):
    def test_empty_plan_fallback_preserves_all_theme_sections_without_prefix_duplication(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a"], target_minutes=5,
            theme="店へ到着する。\n\nパンケーキを食べる。\n\n次回の約束をして解散する。",
        )
        with patch("server.modules.llm_client.openai_text_completion", return_value=""):
            plan = create_draft_plan(
                request, cast_context=[{"cast": "A", "name": "彩"}], chunk_count=1,
                target_characters=1_800, token_budget=2_048, debug_directory=Path("/tmp"),
            )
        self.assertTrue(plan["_planning_fallback_used"])
        self.assertEqual(plan["_planning_fallback_reason"], "empty_response")
        self.assertEqual(len(plan["_source_sections"]), 3)
        fallback_texts = [beat for chapter in plan["chapters"] for beat in chapter["beats"]]
        self.assertEqual(fallback_texts[:3], [
            section["text"] for section in draft_theme_sections(request.theme)
        ])
        self.assertIsNone(plan["_author_ending"])
        self.assertIn("次回の約束をして解散する。", fallback_texts)

    def test_partial_plan_is_accepted_without_exposing_technical_block_count(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a", "cast-b"],
            target_minutes=1,
            theme="教室で答えを相談する。",
        )
        response = "\n".join((
            "TITLE|放課後の相談",
            "CAST_CONTEXT|A|相談役|落ち着いて相手の話を聞く人物。",
            "CHAPTER|1|相談の始まり",
            "OBJECTIVE|問題を確認する",
            "BEAT|二人が問題を読み直す",
            "END_CHAPTER",
        ))
        with patch("server.modules.llm_client.openai_text_completion", return_value=response) as completion:
            plan = create_draft_plan(
                request,
                cast_context=[{"cast": "A", "name": "彩"}, {"cast": "B", "name": "莉里"}],
                chunk_count=25,
                target_characters=12_960,
                token_budget=2_048,
                debug_directory=Path("/tmp"),
            )
        completion.assert_called_once()
        self.assertEqual(completion.call_args.kwargs["max_tokens"], 2_048)
        self.assertEqual(len(plan["chapters"]), 1)
        planning_user = completion.call_args.kwargs["user"]
        self.assertNotIn("chunk_count", planning_user)
        self.assertNotIn("required_chapters", planning_user)
        self.assertNotIn("target_spoken_characters", planning_user)

    def test_dialogue_request_uses_a_stable_hardware_safe_block(self) -> None:
        self.assertEqual(fixed_dialogue_block_characters(150, 24_576), 160)
        self.assertEqual(fixed_dialogue_block_characters(1_440, 24_576), 1_440)
        self.assertEqual(fixed_dialogue_block_characters(4_000, 24_576), 4_000)
        self.assertEqual(dialogue_output_token_budget(2_000, 24_576), 5_656)

    def test_dialogue_acceptance_keeps_whole_lines_within_remaining_target(self) -> None:
        dialogue = {
            "lines": [
                {"character_id": "cast-a", "text": "短い一行。"},
                {"character_id": "cast-b", "text": "長" * 171},
            ]
        }
        self.assertEqual(
            limit_draft_dialogue_characters(dialogue, 10)["lines"],
            [{"character_id": "cast-a", "text": "短い一行。"}],
        )

    def test_simplified_chinese_detection_avoids_valid_japanese_shinjitai(self) -> None:
        dialogue = {"lines": [{"text": "纱良は生还した。声を聞いて担当する。"}]}
        self.assertEqual(draft_dialogue_simplified_glyphs(dialogue), {"纱", "还"})

    def test_priority_uses_spoken_characters_not_alias_order(self) -> None:
        priorities = {"cast-a": "standard", "cast-b": "main", "cast-c": "supporting"}
        valid = {
            "lines": [
                {"character_id": "cast-a", "text": "短い台詞。"},
                {"character_id": "cast-b", "text": "メインキャストが最も長く話す台詞です。"},
                {"character_id": "cast-c", "text": "中くらいの台詞です。"},
            ]
        }
        self.assertTrue(draft_priority_is_satisfied(valid, priorities))
        invalid = {
            "lines": [
                {"character_id": "cast-a", "text": "標準キャストがメインよりも長く話してしまう台詞です。"},
                {"character_id": "cast-b", "text": "短い。"},
                {"character_id": "cast-c", "text": "中くらいの台詞です。"},
            ]
        }
        self.assertFalse(draft_priority_is_satisfied(invalid, priorities))

    def test_overlong_valid_dialogue_skips_repair_and_is_unchanged(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a", "cast-b"],
            target_minutes=1,
            theme="教室で数学の答えを相談する。",
        )
        source = [
            {
                "chapter": {"title": "教室"},
                "dialogue": {
                    "lines": [
                        {"line_id": "C001L001", "character_id": "cast-a", "text": "説明を繰り返します。" * 20},
                        {"line_id": "C001L002", "character_id": "cast-b", "text": "結論を確認します。" * 24},
                    ]
                },
                "spoken": 0,
            }
        ]
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion") as completion,
        ):
            repaired = repair_draft_dialogue(
                request,
                job_id="test-job",
                cast_context=[
                    {"cast": "A", "name": "少佐", "preferences": {"priority": "standard"}},
                    {"cast": "B", "name": "Riri", "preferences": {"priority": "main"}},
                ],
                plan={"story_bible": "数学の授業", "chapters": []},
                drafted_chapters=source,
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
                priority_by_cast_id={"cast-a": "standard", "cast-b": "main"},
                token_budget=2_048,
                debug_directory=Path("/tmp"),
            )
        self.assertIs(repaired, source)
        completion.assert_not_called()

    def test_global_repair_does_not_rewrite_simplified_glyph_rows(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a", "cast-b"],
            target_minutes=1,
            theme="修復テストです。",
        )
        chapters = [
            {
                "chapter": {"title": "教室"},
                "dialogue": {
                    "lines": [
                        {"line_id": "C001L001", "character_id": "cast-a", "text": "この台詞はそのまま残します。"},
                        {"line_id": "C001L002", "character_id": "cast-b", "text": "纱良の答えを信じます。" * 4},
                    ]
                },
                "spoken": 0,
            }
        ]
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion") as completion,
        ):
            repaired = repair_draft_dialogue(
                request,
                job_id="test-job",
                cast_context=[{"cast": "A", "name": "少佐"}, {"cast": "B", "name": "Riri"}],
                plan={"chapters": []},
                drafted_chapters=chapters,
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
                priority_by_cast_id={"cast-a": "standard", "cast-b": "main"},
                token_budget=2_048,
                debug_directory=Path("/tmp"),
            )
        self.assertIs(repaired, chapters)
        completion.assert_not_called()

    def test_global_repair_keeps_valid_additions_from_one_partial_response(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a", "cast-b"],
            target_minutes=1,
            theme="放課後に相談する。",
        )
        chapters = [{
            "chapter": {"title": "教室"},
            "dialogue": {"lines": [
                {"line_id": "C001L001", "character_id": "cast-a", "text": "一人で考えてみます。"},
            ]},
            "spoken": 10,
        }]
        response = "\n".join((
            "説明文は無視される",
            "C001|B|😊一緒に考えましょう。",
            "C999|A|存在しない章への追加",
        ))
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=response) as completion,
        ):
            repaired = repair_draft_dialogue(
                request,
                job_id="test-job",
                cast_context=[{"cast": "A", "name": "彩"}, {"cast": "B", "name": "莉里"}],
                plan={"chapters": []},
                drafted_chapters=chapters,
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
                priority_by_cast_id={"cast-a": "standard", "cast-b": "main"},
                token_budget=2_048,
                debug_directory=Path("/tmp"),
            )
        completion.assert_called_once()
        self.assertEqual(repaired[0]["dialogue"]["lines"][0]["text"], "一人で考えてみます。")
        self.assertEqual(repaired[0]["dialogue"]["lines"][1]["character_id"], "cast-b")
        self.assertEqual(repaired[0]["dialogue"]["lines"][1]["text"], "一緒に考えましょう。")
        self.assertNotIn("retry_corrections", completion.call_args.kwargs["user"])

    def test_stream_loop_detection_allows_one_silence_but_stops_a_loop(self) -> None:
        one = "::LINE cast-a\nTEXT|……。\n::END"
        self.assertIsNone(draft_dialogue_loop_reason(one))
        repeated = "\n".join(one for _ in range(12))
        self.assertIsNotNone(draft_dialogue_loop_reason(repeated))
        current_protocol_loop = "\n".join("B|……。" for _ in range(12))
        self.assertIsNotNone(draft_dialogue_loop_reason(current_protocol_loop))
        performance = "\n".join("::PERFORMANCE C001L001" for _ in range(10))
        self.assertIsNotNone(draft_performance_loop_reason(performance))

    def test_first_dialogue_shot_loop_reports_model_compatibility(self) -> None:
        reason = "同じ台詞が12回連続しました。"
        message = first_dialogue_shot_compatibility_message(0, 1, reason)
        self.assertIsNotNone(message)
        self.assertIn("性能または相性", message or "")
        self.assertIsNone(first_dialogue_shot_compatibility_message(0, 2, reason))
        self.assertIsNone(first_dialogue_shot_compatibility_message(1, 1, reason))
        self.assertIsNone(first_dialogue_shot_compatibility_message(0, 1, None))

    def test_job_keeps_short_output_at_the_finite_dialogue_budget(self) -> None:
        job_id = "draft_job_short_output_test"
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            speech_rate=0.6,
            theme="不足文字数を確認するテストです。",
        )
        characters = [{"id": "cast-a", "name": "A", "profileDetails": {}}]
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "planning",
                "cancelRequested": False,
                "overallProgress": 0.0,
                "generatedCharacters": 0,
                "chunks": [],
                "appendedLines": 0,
                "estimatedSeconds": 0,
            }
        calls = itertools.count(1)

        def short_dialogue(*_args, **_kwargs):
            number = next(calls)
            return ({"lines": [{"character_id": "A", "text": f"短い台詞{number}です。"}]}, None)

        try:
            with (
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp")),
                patch("server.modules.draft_algorithms.safe_draft_chapter_characters", return_value=1_000),
                patch("server.modules.draft_planning.select_draft_optional_context", return_value={"cast-a": set()}),
                patch(
                    "server.modules.draft_planning.create_draft_plan",
                    autospec=True,
                    return_value={"title": "不足", "chapters": [{"title": "一章"}]},
                ),
                patch("server.modules.draft_dialogue.generate_draft_dialogue", side_effect=short_dialogue),
                patch("server.modules.draft_algorithms.has_excessive_draft_repetition", return_value=False),
                patch(
                    "server.modules.draft_algorithms.remove_repeated_draft_dialogue",
                    side_effect=lambda dialogue, _prior: (dialogue, 0),
                ),
                patch("server.modules.draft_performance.direct_draft_performance", return_value=[{
                    "id": "scene-short", "title": "一章", "lines": [{"id": "line-short", "characterId": "cast-a",
                    "text": "短い台詞", "takes": [], "selectedTakeId": None}],
                }]) as performance,
                patch("server.modules.project_repository.read_project", return_value={"title": "", "scenes": []}),
                patch("server.modules.project_repository.write_project"),
            ):
                run_draft_job(job_id, request, characters)
            with DRAFT_JOBS_LOCK:
                job = DRAFT_JOBS[job_id]
            self.assertLessEqual(next(calls) - 1, job["plannedDialogueCalls"])
            self.assertEqual(job["predictedCalls"], 2)
            self.assertEqual(job["plannedDialogueCalls"], 5)
            self.assertEqual(job["status"], "completed")
            self.assertFalse(job["targetReached"])
            self.assertFalse(job["lengthAccepted"])
            self.assertIn("incomplete_developments", job["partialReason"])
            performance.assert_called_once()
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_job_does_not_turn_an_unusable_dialogue_response_into_a_format_retry(self) -> None:
        job_id = "draft_job_unusable_output_test"
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="形式不一致を再試行しないテストです。",
        )
        characters = [{"id": "cast-a", "name": "A", "profileDetails": {}}]
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "planning",
                "cancelRequested": False,
                "overallProgress": 0.0,
                "generatedCharacters": 0,
                "chunks": [],
                "appendedLines": 0,
                "estimatedSeconds": 0,
            }
        try:
            with (
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp")),
                patch("server.modules.draft_algorithms.safe_draft_chapter_characters", return_value=1_000),
                patch("server.modules.draft_planning.select_draft_optional_context", return_value={"cast-a": set()}),
                patch(
                    "server.modules.draft_planning.create_draft_plan",
                    autospec=True,
                    return_value={"title": "不一致", "chapters": [{"title": "一章"}]},
                ),
                patch(
                    "server.modules.draft_dialogue.generate_draft_dialogue",
                    return_value=({"lines": []}, None),
                ) as dialogue,
                patch("server.modules.draft_performance.direct_draft_performance") as performance,
            ):
                run_draft_job(job_id, request, characters)
            self.assertEqual(dialogue.call_count, 2)
            # Coverage and ending own different sources; neither is a format retry.
            self.assertNotEqual(dialogue.call_args_list[0].kwargs["chapter"],
                                dialogue.call_args_list[1].kwargs["chapter"])
            performance.assert_not_called()
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["status"], "failed")
                self.assertEqual(DRAFT_JOBS[job_id]["failureCode"], "draft_no_usable_output")
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_job_keeps_short_valid_responses_without_exceeding_call_budget(self) -> None:
        job_id = "draft_job_continuation_target_test"
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            speech_rate=0.6,
            theme="継続生成を確認するテストです。",
        )
        characters = [{"id": "cast-a", "name": "A", "profileDetails": {}}]
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "planning",
                "cancelRequested": False,
                "overallProgress": 0.0,
                "generatedCharacters": 0,
                "chunks": [],
                "appendedLines": 0,
                "estimatedSeconds": 0,
                "performanceTextCorrections": 0,
            }
        calls = itertools.count(1)

        def short_dialogue(*_args, **_kwargs):
            number = next(calls)
            return (
                {
                    "lines": [
                        {
                            "character_id": "A",
                            "text": f"第{number}回の続きとして新しい出来事を丁寧に語ります。" + "あ" * 45,
                        }
                    ]
                },
                None,
            )

        def performance(*_args, **kwargs):
            index = kwargs["chapter_index"]
            return [
                {
                    "id": f"scene-{index}",
                    "title": "一章",
                    "lines": [
                        {
                            "id": "line-1",
                            "characterId": "cast-a",
                            "text": "確定済み台詞",
                            "stageDirection": "自然に話す",
                            "speechRate": 1.0,
                            "gapSeconds": 0.7,
                            "takes": [],
                            "selectedTakeId": None,
                        }
                    ],
                }
            ]

        try:
            with (
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp")),
                patch("server.modules.draft_algorithms.safe_draft_chapter_characters", return_value=1_000),
                patch("server.modules.draft_planning.select_draft_optional_context", return_value={"cast-a": set()}),
                patch(
                    "server.modules.draft_planning.create_draft_plan",
                    autospec=True,
                    return_value={"title": "継続", "chapters": [{"title": "一章"}]},
                ),
                patch("server.modules.draft_dialogue.generate_draft_dialogue", side_effect=short_dialogue),
                patch("server.modules.draft_algorithms.has_excessive_draft_repetition", return_value=False),
                patch(
                    "server.modules.draft_algorithms.remove_repeated_draft_dialogue",
                    side_effect=lambda dialogue, _prior: (dialogue, 0),
                ),
                patch("server.modules.draft_performance.direct_draft_performance", side_effect=performance),
                patch("server.modules.project_repository.read_project", return_value={"title": "", "scenes": []}),
                patch("server.modules.project_repository.write_project"),
            ):
                run_draft_job(job_id, request, characters)
            with DRAFT_JOBS_LOCK:
                job = DRAFT_JOBS[job_id]
            self.assertEqual(job["status"], "completed", job)
            self.assertLessEqual(next(calls) - 1, job["plannedDialogueCalls"])
            self.assertEqual(job["predictedCalls"], 2)
            self.assertEqual(job["plannedDialogueCalls"], 5)
            self.assertFalse(job["lengthAccepted"])
            self.assertIn("incomplete_developments", job["partialReason"])
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_whole_job_progress_never_resets_between_phases(self) -> None:
        dialogue = [
            draft_dialogue_overall_progress(0, 4_000),
            draft_dialogue_overall_progress(2_000, 4_000),
            draft_dialogue_overall_progress(4_000, 4_000),
            draft_dialogue_overall_progress(6_000, 4_000),
        ]
        performance = [
            draft_performance_overall_progress(0, 4),
            draft_performance_overall_progress(2, 4),
            draft_performance_overall_progress(4, 4),
        ]
        progress = [0.0, DRAFT_PROGRESS_CONTEXT, DRAFT_PROGRESS_PLANNING] + dialogue + performance
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(DRAFT_PROGRESS_CONTEXT, 10.0)
        self.assertEqual(DRAFT_PROGRESS_PLANNING, 20.0)
        self.assertEqual(dialogue[0], DRAFT_PROGRESS_DIALOGUE_START)
        self.assertEqual(dialogue[-1], 90.0)
        self.assertEqual(performance[0], 95.0)
        self.assertEqual(performance[-1], 99.0)

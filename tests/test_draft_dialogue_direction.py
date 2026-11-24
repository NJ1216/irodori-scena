from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch


from server.app import (
    DRAFT_JOBS,
    DRAFT_JOBS_LOCK,
    DraftRequest,
    add_draft_text_corrections,
    draft_text_cast_context,
    draft_dialogue_cast_context,
    draft_performance_cast_context,
    direct_draft_performance,
    normalize_draft_dialogue,
    generate_draft_dialogue,
)


class DraftDialogueDirectionTests(unittest.TestCase):
    def test_phase_specific_cast_context_removes_optional_material_from_performance(self) -> None:
        context = [{
            "cast": "A", "name": "莉里",
            "profile": "職業: 書店員\n一人称: 私\n性格: 慎重\n話し方: 丁寧\n趣味: 天体観測\n背景: 過去の事件",
            "reader_facing_introduction_seed": "莉里は、書店員を務める慎重な人物。",
            "relations": [{"target": "B", "address": "先輩"}],
            "preferences": {"emoji": "積極的に使う", "priority": "main"},
        }]
        dialogue = draft_dialogue_cast_context(context)
        performance = draft_performance_cast_context(context)
        self.assertNotIn("reader_facing_introduction_seed", dialogue[0])
        self.assertIn("趣味: 天体観測", dialogue[0]["profile"])
        self.assertNotIn("趣味", str(performance))
        self.assertNotIn("背景", str(performance))
        self.assertNotIn("職業", str(performance))
        self.assertNotIn("introduction", str(performance))
        self.assertIn("一人称: 私", performance[0]["delivery_constraints"])
        self.assertEqual(performance[0]["relations"], context[0]["relations"])
    def test_dialogue_is_immutable_and_gets_global_line_ids(self) -> None:
        dialogue = normalize_draft_dialogue(
            {"lines": [{"line_id": "L001", "character_id": "Riri", "text": "😊おはよう……。"}]},
            permitted={"cast-a"},
            character_name_to_id={"Riri": "cast-a"},
            chapter_index=1,
        )
        self.assertEqual(
            dialogue["lines"],
            [{"line_id": "C002L001", "character_id": "cast-a", "text": "おはよう……。"}],
        )

    def test_dialogue_normalization_ignores_legacy_simultaneous_markers(self) -> None:
        dialogue = normalize_draft_dialogue(
            {"lines": [
                {"character_id": "A", "text": "せーの！", "simultaneous_marker": "S1"},
                {"character_id": "B", "text": "はい！", "simultaneous_marker": "S1"},
            ]},
            permitted={"cast-a", "cast-b"}, character_name_to_id={"A": "cast-a", "B": "cast-b"}, chapter_index=0,
        )
        self.assertTrue(all("simultaneous_candidate_id" not in line for line in dialogue["lines"]))
        self.assertEqual([line["text"] for line in dialogue["lines"]], ["せーの！", "はい！"])
    def test_dialogue_prompt_bans_unicode_emoji_and_normalization_removes_all_of_them(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="絵文字を除去するテストテーマです。",
        )
        with patch(
            "server.modules.llm_client.openai_stream_text_completion", return_value="A|😊☔おはよう…！"
        ) as completion:
            raw, _ = generate_draft_dialogue(
                request,
                cast_context=[{"cast": "A", "name": "莉里", "preferences": {"priority": "standard"}}],
                plan={"story_bible": "テスト", "chapters": []},
                chapter={"title": "導入", "beats": ["挨拶する"]},
                chapter_index=0,
                requested_characters=120,
                remaining_characters=120,
                accepted_dialogue={"lines": []},
                continuity_state="",
                token_budget=2048,
                cast_alias_by_id={"cast-a": "A"},
            )
        normalized = normalize_draft_dialogue(
            raw, permitted={"cast-a"}, character_name_to_id={"A": "cast-a"}, chapter_index=0
        )
        self.assertIn("Unicode絵文字を一切出力しない", completion.call_args.kwargs["system"])
        self.assertIn("約45文字を目安", completion.call_args.kwargs["system"])
        self.assertNotIn("150文字", completion.call_args.kwargs["system"])
        self.assertEqual(normalized["lines"][0]["text"], "おはよう…！")

    def test_dialogue_prompt_uses_only_short_cast_aliases(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["character_long_internal_id"],
            target_minutes=1,
            theme="短縮プロトコルを確認するテストテーマです。",
        )
        cast_context = [{"cast": "A", "name": "Riri", "profile": "一人称: リリ"}]
        with patch(
            "server.modules.llm_client.openai_stream_text_completion", return_value="A|こんにちは。"
        ) as completion:
            dialogue, loop_reason = generate_draft_dialogue(
                request,
                cast_context=cast_context,
                plan={"story_bible": "テスト", "chapters": []},
                chapter={"title": "導入", "beats": ["挨拶する"]},
                chapter_index=0,
                requested_characters=120,
                remaining_characters=120,
                accepted_dialogue={"lines": []},
                continuity_state="",
                token_budget=2048,
                cast_alias_by_id={"character_long_internal_id": "A"},
            )
        self.assertIsNone(loop_reason)
        self.assertEqual(dialogue["lines"][0]["character_id"], "A")
        sent = completion.call_args.kwargs
        self.assertNotIn("character_long_internal_id", str(sent["user"]))
        self.assertIn("NORMAL|A|台詞本文", sent["system"])
        self.assertNotIn("SIM:", sent["system"])
        self.assertNotIn("合図を通常の一行", sent["system"])
        request_fields = sent["user"]["sections"][-1]["accepted_dialogue_and_current_request"]
        self.assertEqual(request_fields["recommended_new_line_count"], 3)
        self.assertNotIn("remaining_spoken_characters_for_chapter", request_fields)

    def test_ai_draft_performance_accepts_chunk_scoped_simultaneous_cue(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="同時発話を演技工程で判定します。", simultaneous_cues=True,
        )
        dialogue = {"lines": [
            {"line_id": "C001L001", "character_id": "cast-a", "text": "せーの！"},
            {"line_id": "C001L002", "character_id": "cast-b", "text": "はい！"},
        ]}
        response = (
            "L1|rate=1.00|gap=0.70|direction=合図する|cue=SIM:S1\n"
            "L2|rate=1.10|gap=0.80|direction=応じる|cue=SIM:S1"
        )
        with (
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=response) as completion,
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[{"cast": "A", "name": "甲"}, {"cast": "B", "name": "乙"}],
                chapter={"title": "導入"}, dialogue=dialogue, lookahead_lines=[],
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"}, prior_performance_state="", token_budget=2048,
                debug_directory=Path("/tmp"), chapter_index=0,
            )
        lines = scenes[0]["lines"]
        self.assertEqual(lines[0]["cueId"], lines[1]["cueId"])
        self.assertEqual([line["startOffsetSeconds"] for line in lines], [0.0, 0.0])
        self.assertIn("cue=SIM:S1", completion.call_args.kwargs["system"])
        self.assertIn("emoji, rate, gap, direction, cue fields", completion.call_args.kwargs["system"])
        self.assertNotIn("Use only emoji, rate, gap, direction fields", completion.call_args.kwargs["system"])
        self.assertIn("実演している場合", completion.call_args.kwargs["system"])

    def test_incomplete_cue_discards_only_cue_fields(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b", "cast-c"], target_minutes=1,
            theme="欠落候補を確認します。", simultaneous_cues=True,
        )
        dialogue = {"lines": [
            {"line_id": f"C001L00{i}", "character_id": f"cast-{name}", "text": text}
            for i, (name, text) in enumerate((("a", "一"), ("b", "二"), ("c", "三")), 1)
        ]}
        response = "L1|rate=1.00|direction=一つ目|cue=SIM:S1\nL2|rate=1.10|direction=二つ目|cue=SIM:S1"
        with (
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=response),
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[], chapter={"title": "導入"}, dialogue=dialogue,
                lookahead_lines=[], cast_alias_by_id={"cast-a": "A", "cast-b": "B", "cast-c": "C"},
                prior_performance_state="", token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        lines = scenes[0]["lines"]
        self.assertTrue(all("cueId" not in line for line in lines))
        self.assertEqual((lines[0]["speechRate"], lines[0]["stageDirection"]), (1.0, "一つ目"))

    def test_performance_prompt_uses_short_line_alias_and_compact_result(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["character_long_internal_id"],
            target_minutes=1,
            theme="演技プロトコルを確認するテストテーマです。",
        )
        dialogue = {
            "lines": [
                {
                    "line_id": "C001L001",
                    "character_id": "character_long_internal_id",
                    "text": "おはよう……。",
                }
            ]
        }
        compact = "L1|emoji=😊@おはよう|rate=0.98|gap=0.72|direction=相手を安心させるように"
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=compact) as completion,
        ):
            scenes = direct_draft_performance(
                request,
                job_id="test-job",
                cast_context=[{"cast": "A", "name": "Riri"}],
                chapter={"title": "導入"},
                dialogue=dialogue,
                lookahead_lines=[],
                cast_alias_by_id={"character_long_internal_id": "A"},
                prior_performance_state="",
                token_budget=2048,
                debug_directory=Path("/tmp"),
                chapter_index=0,
            )
        self.assertEqual(scenes[0]["lines"][0]["speechRate"], 0.98)
        sections = {key: value for section in completion.call_args.kwargs["user"]["sections"]
                    for key, value in section.items()}
        sent_dialogue = sections["lines"]
        self.assertIn("変更対象|L1|Riri|おはよう……。", sent_dialogue)
        self.assertNotIn("C001L001", sent_dialogue)

    def test_emoji_cast_preference_is_sent_to_performance_but_not_dialogue(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="絵文字設定の受け渡しを確認するテーマです。",
            emoji_expressions=True,
        )
        cast_context = [{"cast": "A", "name": "莉里", "preferences": {"emoji": "許可", "priority": "standard"}}]
        dialogue = {"lines": [{"line_id": "C001L001", "character_id": "cast-a", "text": "おはよう。"}]}
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value="L1|emoji=😊@おはよう|rate=1.0|gap=0.7|direction=明るく") as completion,
        ):
            direct_draft_performance(
                request, job_id="test-job", cast_context=cast_context, chapter={"title": "導入"}, dialogue=dialogue,
                lookahead_lines=[], cast_alias_by_id={"cast-a": "A"}, prior_performance_state="", token_budget=2048,
                debug_directory=Path("/tmp"), chapter_index=0,
            )
        sent = completion.call_args.kwargs
        sections = {key: value for section in sent["user"]["sections"] for key, value in section.items()}
        self.assertIn("許可EMOJI", sections["request_settings"])
        self.assertIn("emoji uses", sent["system"])
        self.assertEqual(sections["participating_casts"], cast_context)
        self.assertIn("📢は叫び・大声・強調を表すEMOJIではない", sent["system"])
        self.assertIn("莉里|おはよう。", sections["lines"])
        self.assertNotIn("emoji", draft_text_cast_context(cast_context)[0]["preferences"])

    def test_draft_performance_applies_compound_anchor_emoji_with_high_rate(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="複合EMOJI演出のテストです。",
            emoji_expressions=True,
            allowed_emojis=["🐢", "🥺", "😖"],
        )
        dialogue = {"lines": [{"line_id": "C001L001", "character_id": "cast-a", "text": "その言葉を聞かせて。"}]}
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch(
                "server.modules.llm_client.openai_stream_text_completion",
                return_value="L1|emoji=🐢🐢🥺😖@言葉|rate=1.30|gap=0.70|direction=勢いよく話しつつ言葉だけためらう",
            ) as completion,
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[{"cast": "A", "name": "莉里"}], chapter={"title": "導入"},
                dialogue=dialogue, lookahead_lines=[], cast_alias_by_id={"cast-a": "A"}, prior_performance_state="",
                token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        line = scenes[0]["lines"][0]
        self.assertEqual(line["text"], "その🐢🐢🥺言葉を聞かせて。")
        self.assertEqual(line["speechRate"], 1.3)
        self.assertIn("高いrateでもためらわせたい", completion.call_args.kwargs["system"])

    def test_performance_keeps_valid_fields_when_rate_is_invalid(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-c"],
            target_minutes=1,
            theme="括弧書きを保持する演技テストです。",
        )
        dialogue = {
            "lines": [
                {
                    "line_id": "C001L039",
                    "character_id": "cast-c",
                    "text": "（小声で）莉里さん、符号のところから。",
                }
            ]
        }
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch(
                "server.modules.llm_client.openai_stream_text_completion",
                return_value="L1|rate=速い|gap=0.50|direction=そっと囁く",
            ) as completion,
        ):
            scenes = direct_draft_performance(
                request,
                job_id="test-job",
                cast_context=[{"cast": "C", "name": "紗良"}],
                chapter={"title": "導入"},
                dialogue=dialogue,
                lookahead_lines=[],
                cast_alias_by_id={"cast-c": "C"},
                prior_performance_state="",
                token_budget=2048,
                debug_directory=Path("/tmp"),
                chapter_index=0,
            )
        completion.assert_called_once()
        line = scenes[0]["lines"][0]
        self.assertEqual(line["text"], "（小声で）莉里さん、符号のところから。")
        self.assertNotIn("speechRate", line)
        self.assertEqual((line["gapSeconds"], line["stageDirection"]), (0.5, "そっと囁く"))

    def test_performance_constraints_clamp_numbers_and_filter_emojis(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="詳細設定を確認するテストテーマです。",
            performance_speech_rate_min=0.9,
            performance_speech_rate_max=1.0,
            performance_gap_min=1.0,
            performance_gap_max=3.0,
            allowed_emojis=["😊"],
        )
        dialogue = {"lines": [{"line_id": "C001L022", "character_id": "cast-a", "text": "おはよう。"}]}
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch(
                "server.modules.llm_client.openai_stream_text_completion",
                return_value="L1|emoji=☁️@おはよう|rate=0.80|gap=5.0|direction=明るく",
            ) as completion,
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[{"cast": "A", "name": "莉里"}], chapter={"title": "導入"},
                dialogue=dialogue, lookahead_lines=[], cast_alias_by_id={"cast-a": "A"}, prior_performance_state="",
                token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        line = scenes[0]["lines"][0]
        self.assertEqual((line["speechRate"], line["text"], line["stageDirection"]), (0.9, "おはよう。", "明るく"))
        self.assertNotIn("gapSeconds", line)
        completion.assert_called_once()
        settings = completion.call_args.kwargs["user"]["sections"][0]["request_settings"]
        self.assertIn("0.90〜1.00", settings)
        self.assertIn("1.00〜3.00", settings)
        self.assertNotIn("☁️", settings)

    def test_performance_keeps_valid_sibling_fields_when_one_field_is_invalid(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model", character_ids=["cast-a"], target_minutes=1,
            theme="再試行のマージ範囲を確認するテーマです。",
        )
        dialogue = {"lines": [
            {"line_id": "C001L022", "character_id": "cast-a", "text": "先に決まった台詞。"},
            {"line_id": "C001L040", "character_id": "cast-a", "text": "あとで直す台詞。"},
        ]}
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch(
                "server.modules.llm_client.openai_stream_text_completion",
                return_value="L1|rate=1.00|gap=0.70|direction=穏やかに\nL2|rate=不明|gap=0.70|direction=急いで",
            ) as completion,
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[{"cast": "A", "name": "莉里"}], chapter={"title": "導入"},
                dialogue=dialogue, lookahead_lines=[], cast_alias_by_id={"cast-a": "A"}, prior_performance_state="",
                token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        self.assertEqual(scenes[0]["lines"][0]["speechRate"], 1.0)
        self.assertEqual(scenes[0]["lines"][0]["gapSeconds"], 0.7)
        self.assertNotIn("speechRate", scenes[0]["lines"][1])
        self.assertEqual(scenes[0]["lines"][1]["gapSeconds"], 0.7)
        self.assertEqual(scenes[0]["lines"][1]["stageDirection"], "急いで")
        completion.assert_called_once()

    def test_chapter_two_l12_unapproved_rewrite_does_not_stop_performance(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="第2章の表記フォールバックを確認するテーマです。",
        )
        dialogue = {
            "lines": [
                {
                    "line_id": "C002L012",
                    "character_id": "cast-a",
                    "text": "サウマへ行こう。",
                }
            ]
        }
        corrections: list[int] = []
        # The reply changes more than the typo itself, so the chapter should
        # complete with the original text and no model-authored emoji.
        response = "L1|rate=1.00|gap=0.70|direction=誘うように明るく"
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=response) as completion,
        ):
            scenes = direct_draft_performance(
                request,
                job_id="test-job",
                cast_context=[{"cast": "A", "name": "莉里"}],
                chapter={"title": "第2章"},
                dialogue=dialogue,
                lookahead_lines=[],
                cast_alias_by_id={"cast-a": "A"},
                prior_performance_state="",
                token_budget=2048,
                debug_directory=Path("/tmp"),
                chapter_index=1,
                on_text_corrections=corrections.append,
            )
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(scenes[0]["lines"][0]["text"], "サウマへ行こう。")
        self.assertEqual(corrections, [])

    def test_direct_performance_keeps_the_verified_dialogue_text(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="表記修正件数を確認するテーマです。",
        )
        dialogue = {
            "lines": [
                {
                    "line_id": "C001L001",
                    "character_id": "cast-a",
                    "text": "サウマで休もう。",
                }
            ]
        }
        corrections: list[int] = []
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch(
                "server.modules.llm_client.openai_stream_text_completion",
                return_value="L1|rate=1.00|gap=0.70|direction=穏やかに",
            ),
        ):
            direct_draft_performance(
                request,
                job_id="test-job",
                cast_context=[{"cast": "A", "name": "莉里"}],
                chapter={"title": "第1章"},
                dialogue=dialogue,
                lookahead_lines=[],
                cast_alias_by_id={"cast-a": "A"},
                prior_performance_state="",
                token_budget=2048,
                debug_directory=Path("/tmp"),
                chapter_index=0,
                on_text_corrections=corrections.append,
            )
        self.assertEqual(corrections, [])

    def test_draft_job_accumulates_accepted_typo_corrections(self) -> None:
        job_id = "draft_job_text_correction_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "performanceTextCorrections": 0}
        try:
            add_draft_text_corrections(job_id, 1)
            add_draft_text_corrections(job_id, 2)
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["performanceTextCorrections"], 3)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

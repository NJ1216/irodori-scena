from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from server.app import DraftRequest, direct_draft_performance, generate_draft_dialogue, normalize_draft_dialogue
from server.modules.direction_fields import performance_direction_policy


class DraftSimultaneousCueRegressionTests(TestCase):
    def test_cues_and_overlaps_have_independent_policy(self) -> None:
        cues_only = DraftRequest(
            character_ids=["cast-a", "cast-b"], target_minutes=1, theme="掛け声",
            simultaneous_cues=True, overlapping_speech=False,
        )
        overlap_only = DraftRequest(
            character_ids=["cast-a", "cast-b"], target_minutes=1, theme="割り込み",
            simultaneous_cues=False, overlapping_speech=True,
        )
        self.assertEqual((performance_direction_policy(cues_only).cue, performance_direction_policy(cues_only).negative_gap), (True, False))
        self.assertEqual(cues_only.performance_gap_min, 0)
        self.assertEqual((performance_direction_policy(overlap_only).cue, performance_direction_policy(overlap_only).negative_gap), (False, True))
        self.assertEqual(overlap_only.performance_gap_min, -2)

    def test_v2_generation_keeps_lead_in_normal_and_groups_different_member_texts(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="掛け声から二人が異なる挨拶を同時に言います。", simultaneous_cues=True,
        )
        response = (
            "NORMAL|A|せーの！||rate=1.00|gap=0.10|direction=合図する\n"
            "SIM:S1|A|やっほ〜！||rate=1.10|gap=0.20|direction=明るく\n"
            "SIM:S1|B|こんにちは！||rate=0.95|gap=0.70|direction=朗らかに"
        )
        with patch("server.modules.llm_client.openai_stream_text_completion", return_value=response):
            raw, _ = generate_draft_dialogue(
                request, cast_context=[{"cast": "A", "name": "甲"}, {"cast": "B", "name": "乙"}],
                plan={"story_bible": "", "chapters": []}, chapter={"title": "挨拶"}, chapter_index=0,
                requested_characters=80, remaining_characters=80, accepted_dialogue={"lines": []},
                continuity_state="", token_budget=2048,
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
            )
        dialogue = normalize_draft_dialogue(
            raw, permitted={"cast-a", "cast-b"},
            character_name_to_id={"A": "cast-a", "B": "cast-b"}, chapter_index=0,
        )
        with patch("server.modules.draft_job_state.update_draft_job"):
            lines = direct_draft_performance(
                request, job_id="v2-cue", cast_context=[], chapter={"title": "挨拶"}, dialogue=dialogue,
                lookahead_lines=[], cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
                prior_performance_state="", token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )[0]["lines"]
        self.assertNotIn("cueId", lines[0])
        self.assertEqual(lines[1]["cueId"], lines[2]["cueId"])
        self.assertEqual([line["text"] for line in lines], ["せーの！", "やっほ〜！", "こんにちは！"])

    def test_integrated_reused_marker_creates_separate_contiguous_cues(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="二組の同時発話を実演します。", simultaneous_cues=True,
        )
        rows = []
        for index, (cast, text, cue) in enumerate((
            ("cast-a", "せーの！", "SIM:S1"), ("cast-b", "はい！", "SIM:S1"),
            ("cast-a", "間の台詞です。", "NONE"),
            ("cast-a", "ありがとう！", "SIM:S1"), ("cast-b", "またね！", "SIM:S1"),
        ), 1):
            rows.append({
                "line_id": f"C001L{index:03d}", "character_id": cast, "text": text,
                "integrated_direction_attempted": True,
                "integrated_direction": {"rate": "1.0", "direction": "明るく", "cue": cue},
                "integrated_direction_source_text": text,
                "integrated_direction_origin": f"R{index}",
                "integrated_direction_next_origin": f"R{index + 1}" if index < 5 else "END",
            })
        with patch("server.modules.draft_job_state.update_draft_job"):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[], chapter={"title": "実演"},
                dialogue={"lines": rows}, lookahead_lines=[],
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"}, prior_performance_state="",
                token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        lines = scenes[0]["lines"]
        self.assertEqual(lines[0]["cueId"], lines[1]["cueId"])
        self.assertEqual(lines[3]["cueId"], lines[4]["cueId"])
        self.assertNotEqual(lines[0]["cueId"], lines[3]["cueId"])
        self.assertNotIn("cueId", lines[2])

    def test_dialogue_prompt_splits_lead_in_from_simultaneous_phrase(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="乾杯する場面を作るテストです。", simultaneous_cues=True,
        )
        with patch("server.modules.llm_client.openai_stream_text_completion", return_value="A|せーの、\nA|乾杯！\nB|乾杯！") as completion:
            generate_draft_dialogue(
                request, cast_context=[{"cast": "A", "name": "甲"}, {"cast": "B", "name": "乙"}],
                plan={"story_bible": "テスト", "chapters": []}, chapter={"title": "乾杯"}, chapter_index=0,
                requested_characters=120, remaining_characters=120, accepted_dialogue={"lines": []},
                continuity_state="", token_budget=2048, cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
            )
        prompt = completion.call_args.kwargs["system"]
        self.assertIn("NORMAL|A|せーの！", prompt)
        self.assertIn("SIM:S1|A|やっほ〜！", prompt)
        self.assertIn("SIM:S1|B|こんにちは！", prompt)
        self.assertIn("合図・カウント・前置きは必ずNORMAL", prompt)
        self.assertIn("同じ文章である必要はない", prompt)
        self.assertIn("完全に同じ `SIM:S1`", prompt)
        self.assertIn("少なくとも一組", prompt)
        self.assertIn("少なくとも一箇所で負のgap", prompt)
        self.assertIn("SAME_1", prompt)

    def test_negative_gap_is_assigned_to_preceding_interrupted_line(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="割り込みを演出するテストです。", simultaneous_cues=True,
        )
        dialogue = {"lines": [
            {"line_id": "C001L001", "character_id": "cast-a", "text": "だから最後まで聞いて――"},
            {"line_id": "C001L002", "character_id": "cast-b", "text": "もう十分だよ。"},
        ]}
        response = "L1|rate=1.00|gap=-0.80|direction=言い切ろうとする\nL2|rate=1.05|gap=0.70|direction=遮って断言する"
        with (
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=response) as completion,
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[], chapter={"title": "対立"}, dialogue=dialogue,
                lookahead_lines=[], cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
                prior_performance_state="", token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        self.assertEqual([line["gapSeconds"] for line in scenes[0]["lines"]], [-0.8, 0.7])
        prompt = str(completion.call_args.kwargs["user"])
        self.assertIn("被せ・割り込みが演出上必要な場合だけ", prompt)
        self.assertIn("直前の先行行のgapへ負値", prompt)
        self.assertIn("cueは複数行の全文を同時開始", prompt)

    def test_cue_survives_extra_returned_lookahead_records(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="同時に笑う実演です。", simultaneous_cues=True,
        )
        dialogue = {"lines": [
            {"line_id": "C001L024", "character_id": "cast-a", "text": "あははは！"},
            {"line_id": "C001L025", "character_id": "cast-b", "text": "あははは！"},
        ]}
        response = (
            "L1|rate=1.20|gap=0.10|direction=声を上げて笑う;cue=SIM:S1\n"
            "L2|rate=1.20|gap=0.10|direction=声を上げて笑う;cue=SIM:S1\n"
            "L3|rate=1.00|gap=0.30|direction=変更不可の直後文脈"
        )
        with (
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=response),
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[], chapter={"title": "実演"}, dialogue=dialogue,
                lookahead_lines=[{"line_id": "C002L001", "character_id": "cast-a", "text": "本当だね。"}],
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"}, prior_performance_state="", token_budget=2048,
                debug_directory=Path("/tmp"), chapter_index=0,
            )
        lines = scenes[0]["lines"]
        self.assertEqual(lines[0]["cueId"], lines[1]["cueId"])

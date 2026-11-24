import unittest

from server.modules.draft_stream_progress import draft_stream_progress_reporter, estimate_streamed_text_characters

from server.app import (
    DRAFT_JOBS,
    DRAFT_JOBS_LOCK,
    draft_generation_target,
    first_packet_request,
    final_block_has_floor_capacity,
    minimum_acceptable_characters,
    next_forward_request,
    maximum_dialogue_calls,
    planned_draft_blocks,
    planning_output_token_budget,
    resilient_planned_draft_blocks,
    second_packet_request,
    required_draft_developments,
    validate_forward_plan,
)
from server.draft_protocol import parse_dialogue_protocol


class DraftForwardPolicyTests(unittest.TestCase):
    def test_structured_progress_counts_complete_and_open_text_strings_only(self) -> None:
        content = '{"lines":[{"speaker":"A","text":"完成\\u3057た"},{"text":"途中です'
        self.assertEqual(estimate_streamed_text_characters(content), 8)

    def test_structured_progress_ignores_other_string_fields(self) -> None:
        content = '{"title":"数えない","text":"台詞","direction":"これも数えない"}'
        self.assertEqual(estimate_streamed_text_characters(content), 2)

    def test_streamed_partial_text_updates_estimate_without_advancing_confirmed_progress(self) -> None:
        job_id = "draft_stream_progress_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "generating",
                "phase": "dialogue",
                "overallProgress": 20.0,
                "generatedCharacters": 0,
            }
        try:
            draft_stream_progress_reporter(job_id, 0, {"cast-a": "A"}, 1_000)(
                '{"lines":[{"speaker":"A","text":"' + "あ" * 100
            )
            with DRAFT_JOBS_LOCK:
                job = DRAFT_JOBS[job_id]
                self.assertGreater(job["estimatedGeneratedCharacters"], 0)
                self.assertEqual(job["generatedCharacters"], 0)
                self.assertEqual(job["overallProgress"], 20.0)
                self.assertEqual(job["message"], "応答を確認中")
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_generation_target_adds_ten_percent_and_rounds_up(self) -> None:
        self.assertEqual(draft_generation_target(1800), 1980)
        self.assertEqual(draft_generation_target(1), 2)

    def test_first_packet_requests_twenty_percent_headroom(self) -> None:
        self.assertEqual(first_packet_request(1500, 5000), (1800, None))
        self.assertEqual(first_packet_request(4500, 5000), (5000, "character_ceiling"))

    def test_second_packet_uses_only_first_call_yield_and_seven_percent_headroom(self) -> None:
        requested, measured, remaining, uncapped, reason = second_packet_request(
            generation_target=1981, first_accepted=720, first_requested=1200, max_block=5000)
        self.assertEqual(measured, 0.6)
        self.assertEqual(remaining, 1261)
        self.assertEqual(uncapped, 2249)
        self.assertEqual(requested, 2249)
        self.assertIsNone(reason)

    def test_second_packet_clamps_zero_high_and_low_yield(self) -> None:
        self.assertEqual(second_packet_request(generation_target=1000, first_accepted=0,
            first_requested=0, max_block=5000)[1], 0.25)
        self.assertEqual(second_packet_request(generation_target=1000, first_accepted=50,
            first_requested=1000, max_block=5000)[1], 0.25)
        self.assertEqual(second_packet_request(generation_target=1000, first_accepted=1200,
            first_requested=1000, max_block=5000)[1], 1.0)

    def test_second_packet_records_character_ceiling(self) -> None:
        requested, _, _, uncapped, reason = second_packet_request(
            generation_target=5500, first_accepted=100, first_requested=1000, max_block=5000)
        self.assertGreater(uncapped, 5000)
        self.assertEqual(requested, 5000)
        self.assertEqual(reason, "character_ceiling")

    def test_technical_developments_are_separate_from_six_story_chapters(self) -> None:
        self.assertEqual(required_draft_developments(12_960, 2_074, 6), 25)
        self.assertEqual(maximum_dialogue_calls(25), 30)
    def test_twelve_thousand_character_acceptance_boundary(self) -> None:
        self.assertEqual(minimum_acceptable_characters(12_000), 11_500)
        self.assertGreaterEqual(11_500, minimum_acceptable_characters(12_000))
        self.assertLess(11_499, minimum_acceptable_characters(12_000))

    def test_planned_blocks_use_conservative_initial_yield(self) -> None:
        self.assertEqual(planned_draft_blocks(12_000, 5_000, 0.60), 4)
        self.assertEqual(planned_draft_blocks(12_000, 5_000, 1.00), 3)
        self.assertEqual(planned_draft_blocks(10_800, 2_160, 0.45), 12)

    def test_resilient_plan_has_floor_capacity_and_one_reserve_block(self) -> None:
        self.assertEqual(resilient_planned_draft_blocks(10_800, 2_160), 21)
        self.assertGreaterEqual((21 - 1) * 2_160 * 0.25, 10_800)

    def test_reserve_blocks_stop_only_when_final_floor_capacity_is_enough(self) -> None:
        self.assertFalse(final_block_has_floor_capacity(accepted=10_259, target=10_800, max_block=2_160))
        self.assertTrue(final_block_has_floor_capacity(accepted=10_260, target=10_800, max_block=2_160))

    def test_planning_output_has_generous_late_block_headroom(self) -> None:
        self.assertEqual(planning_output_token_budget(7, 16_000), 8_400)
        self.assertEqual(planning_output_token_budget(20, 32_000), 16_384)
        self.assertEqual(planning_output_token_budget(7, 4_096), 4_096)

    def test_forward_correction_only_increases_later_request(self) -> None:
        requested, observed, accepted_goal = next_forward_request(
            target=12_000, accepted=1_500, remaining_blocks=3, required=160,
            requested_total=3_000, accepted_total=1_500, max_block=5_000,
        )
        self.assertEqual(observed, 0.5)
        self.assertEqual(accepted_goal, 3_500)
        self.assertEqual(requested, 5_000)

    def test_forward_correction_keeps_seven_percent_final_call_headroom(self) -> None:
        requested, observed, accepted_goal = next_forward_request(
            target=4_320, accepted=4_121, remaining_blocks=1, required=160,
            requested_total=4_686, accepted_total=4_121, max_block=2_160,
        )
        self.assertAlmostEqual(observed, 4_121 / 4_686)
        self.assertEqual(accepted_goal, 199)
        self.assertEqual(requested, 243)

    def test_plan_shortage_is_not_filled_with_generic_blocks(self) -> None:
        plan = {"chapters": [{"opening_state": "開始", "closing_state": "終了", "beats": ["展開"]}]}
        with self.assertRaisesRegex(ValueError, "生成ブロック数"):
            validate_forward_plan(plan, 2, False)

    def test_six_concrete_developments_are_sufficient_for_a_long_block(self) -> None:
        block = {
            "opening_state": "機能紹介を始める", "closing_state": "紹介を終える",
            "beats": [f"具体的な展開{index}" for index in range(6)],
        }
        plan = {"chapters": [dict(block) for _ in range(7)], "_minimum_beats_per_block": 6}
        self.assertEqual(len(validate_forward_plan(plan, 7, False)), 7)

    def test_integrated_protocol_keeps_valid_siblings_and_development_ids(self) -> None:
        parsed = parse_dialogue_protocol(
            "B1.1|A|有効な台詞です。||rate=1.0|gap=0.7|direction=静かに|cue=NONE\n"
            "BROKEN\n"
            "B1.2|A|次の有効な台詞です。||rate=oops|gap=0.8|direction=NONE|cue=NONE",
            allowed_speakers={"A"},
        )
        self.assertEqual([line["development_id"] for line in parsed["lines"]], ["B1.1", "B1.2"])
        self.assertEqual([line["text"] for line in parsed["lines"]], ["有効な台詞です。", "次の有効な台詞です。"])

    def test_parser_salvages_redundant_chapter_and_development_scope(self) -> None:
        parsed = parse_dialogue_protocol(
            "C2|D2.3|A|章番号を余分に付けた有効な台詞。||rate=1.0|direction=自然に",
            allowed_speakers={"A"},
        )
        self.assertEqual(len(parsed["lines"]), 1)
        self.assertEqual(parsed["lines"][0]["character_id"], "A")
        self.assertEqual(parsed["lines"][0]["development_id"], "D2.3")
        self.assertEqual(parsed["lines"][0]["source_chapter_id"], "C2")

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import (
    AiDirectionRequest,
    DraftRequest,
    LineAssistantRequest,
    direct_draft_performance,
    parse_generated_lines,
)
from server.modules.direction_fields import (
    apply_performance_direction,
    normalize_negative_gap_ownership,
    performance_direction_policy,
)


class PerformanceDirectionPolicyTests(unittest.TestCase):
    def _requests(self) -> list[tuple[object, str]]:
        draft = DraftRequest(
            character_ids=["cast-a"], target_minutes=1, theme="共通演出契約を確認するテーマです。",
            cast_settings={"cast-a": {"emoji_expressions": True}}, allowed_emojis=["😊"],
        )
        direction = AiDirectionRequest(
            line_ids=["line-a"], emoji_expressions=True, allowed_emojis=["😊"], overwrite_existing=True,
        )
        assistant = LineAssistantRequest(
            scene_id="scene-a", character_id="cast-a", instruction="自然な一言を追加する。",
            emoji_expressions=True,
        )
        return [(draft, "cast-a"), (direction, "cast-a"), (assistant, "cast-a")]

    def test_three_paths_accept_the_same_independent_direction_fields(self) -> None:
        values = {"emoji": "😊@おはよう", "rate": "0.95", "gap": "0.40", "direction": "明るく"}
        patches = [
            apply_performance_direction(
                performance_direction_policy(request), {"text": "おはよう。"}, values,
                character_id=character_id,
            )
            for request, character_id in self._requests()
        ]
        self.assertEqual(patches, [patches[0]] * 3)
        self.assertEqual(
            patches[0],
            {"text": "😊おはよう。", "speechRate": 0.95, "gapSeconds": 0.4, "stageDirection": "明るく"},
        )

    def test_invalid_siblings_do_not_discard_valid_fields(self) -> None:
        request, character_id = self._requests()[0]
        patch = apply_performance_direction(
            performance_direction_policy(request), {"text": "連絡はuser@example.comへ。"},
            {"emoji": "😊@存在しない", "rate": "broken", "gap": "0.5", "direction": "穏やかに"},
            character_id=character_id,
        )
        self.assertEqual(patch, {"gapSeconds": 0.5, "stageDirection": "穏やかに"})

    def test_line_assistant_accepts_canonical_and_legacy_records(self) -> None:
        canonical = parse_generated_lines(
            "LINE|おはよう。||emoji=😊@おはよう|rate=0.95|gap=0.4|direction=明るく|cue=NONE"
        )
        legacy = parse_generated_lines("LINE|おはよう。|明るく|0.95|0.4|😊@before:おはよう")
        self.assertEqual(canonical[0]["direction_values"]["direction"], "明るく")
        self.assertEqual(legacy[0]["stage_direction"], "明るく")

    def test_current_line_interruption_gap_moves_to_preceding_edge(self) -> None:
        records = [
            ({"text": "説明を続ける。", "gap": 0.5}, {"gap": "0.50", "direction": "得意げに"}),
            ({"text": "ちょっと待って！", "gap": 0.6}, {"gap": "-0.40", "direction": "割り込むように"}),
            ({"text": "今の感じや。", "gap": 0.7}, {"gap": "0.70", "direction": "笑いながら"}),
        ]
        normalized = normalize_negative_gap_ownership(records, default_gap=0.7)
        self.assertEqual([values["gap"] for values in normalized], ["-0.4", "0.6", "0.70"])

    def test_integrated_draft_stores_interruption_on_preceding_line(self) -> None:
        request = DraftRequest(
            character_ids=["souta", "riri"], target_minutes=1,
            theme="Ririが颯太の説明へ被せる場面です。", simultaneous_cues=True,
        )
        dialogue = {"lines": [
            {"line_id": "L1", "character_id": "souta", "text": "説明を続けるで。",
             "integrated_direction_attempted": True,
             "integrated_direction": {"gap": "0.50", "direction": "得意げに"},
             "integrated_direction_source_text": "説明を続けるで。",
             "integrated_direction_origin": "R1", "integrated_direction_next_origin": "R2"},
            {"line_id": "L2", "character_id": "riri", "text": "ちょっと待って！",
             "integrated_direction_attempted": True,
             "integrated_direction": {"emoji": "😆@😆", "gap": "-0.40", "direction": "割り込むように"},
             "integrated_direction_source_text": "ちょっと待って！",
             "integrated_direction_origin": "R2", "integrated_direction_next_origin": "END"},
        ]}
        with patch("server.modules.draft_job_state.update_draft_job"):
            scenes = direct_draft_performance(
                request, job_id="gap-owner", cast_context=[], chapter={"title": "実演"},
                dialogue=dialogue, lookahead_lines=[], cast_alias_by_id={"souta": "A", "riri": "B"},
                prior_performance_state="", token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        first, second = scenes[0]["lines"]
        self.assertEqual((first["gapSeconds"], second["gapSeconds"]), (-0.4, 0.7))
        self.assertEqual(second["text"], "ちょっと待って！")
        self.assertEqual(second["stageDirection"], "割り込むように")

    def test_same_speaker_negative_gap_is_zero_without_changing_sibling_fields(self) -> None:
        values = {"gap": "-0.4", "rate": "broken", "direction": "穏やかに"}
        records = [({"character_id": "a"}, values), ({"character_id": "a"}, {})]
        normalized = normalize_negative_gap_ownership(records, default_gap=0.7)
        self.assertEqual(normalized, [{**values, "gap": "0"}, {}])
        self.assertEqual(values["gap"], "-0.4")

    def test_other_speaker_positive_missing_and_unknown_gaps_are_preserved(self) -> None:
        for speaker, following, gap in [("a", "b", "-0.4"), ("a", "a", "0.5"),
                                         ("a", "a", "0"), ("", "", "-0.4"),
                                         ("a", "a", "broken"), ("a", "a", None)]:
            with self.subTest(speaker=speaker, following=following, gap=gap):
                values = {} if gap is None else {"gap": gap}
                result = normalize_negative_gap_ownership([({"character_id": speaker}, values)],
                    default_gap=0.7, following_row={"character_id": following})
                self.assertEqual(result, [values])

    def test_same_speaker_interruption_is_clamped_after_ownership_moves(self) -> None:
        records = [({"character_id": "a"}, {"gap": "0.5"}),
                   ({"character_id": "a"}, {"gap": "-0.4", "direction": "割り込むように"})]
        result = normalize_negative_gap_ownership(records, default_gap=0.7)
        self.assertEqual([row["gap"] for row in result], ["0", "0.7"])

    def test_same_speaker_across_chunk_boundary_is_clamped(self) -> None:
        result = normalize_negative_gap_ownership([({"character_id": "a"}, {"gap": "-0.4"})],
            default_gap=0.7, following_row={"character_id": "a"})
        self.assertEqual(result, [{"gap": "0"}])

    def test_integrated_draft_applies_same_speaker_rule_before_saving(self) -> None:
        request = DraftRequest(character_ids=["a", "b"], target_minutes=1,
            theme="自己紹介", simultaneous_cues=True)
        lines = []
        for index, speaker in enumerate(["a", "a", "b"]):
            lines.append({"line_id": f"L{index}", "character_id": speaker, "text": f"紹介{index}です。",
                "integrated_direction_attempted": True,
                "integrated_direction": {"gap": "-0.4", "rate": "1.1", "direction": "穏やかに"},
                "integrated_direction_source_text": f"紹介{index}です。",
                "integrated_direction_origin": f"R{index}",
                "integrated_direction_next_origin": f"R{index + 1}" if index < 2 else "END"})
        with patch("server.modules.draft_job_state.update_draft_job"), \
             patch("server.modules.llm_client.openai_stream_text_completion") as llm:
            scenes = direct_draft_performance(request, job_id="same-speaker-gap", cast_context=[],
                chapter={"title": "紹介"}, dialogue={"lines": lines},
                lookahead_lines=[{"line_id": "next", "character_id": "b", "text": "続きです。"}],
                cast_alias_by_id={"a": "A", "b": "B"}, prior_performance_state="",
                token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0)
        result = scenes[0]["lines"]
        self.assertEqual([row["gapSeconds"] for row in result], [0, -0.4, 0])
        self.assertEqual([row["text"] for row in result], [row["text"] for row in lines])
        self.assertTrue(all(row["speechRate"] == 1.1 and row["stageDirection"] == "穏やかに" for row in result))
        llm.assert_not_called()


if __name__ == "__main__":
    unittest.main()

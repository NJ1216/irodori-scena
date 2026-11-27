from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest


from server.app import (
    apply_emoji_annotations,
    assemble_draft_performance,
    estimated_draft_seconds,
    remove_repeated_draft_dialogue,
    remove_repeated_draft_blocks,
    resequence_draft_dialogue,
)


class DraftPerformanceValidationTests(unittest.TestCase):
    def test_annotations_allow_more_than_four_distinct_valid_effects(self) -> None:
        text = apply_emoji_annotations(
            "大事な言葉を、今伝える。",
            [
                {"emoji": "😊", "placement": "line_start", "target": ""},
                {"emoji": "😰", "placement": "before_phrase", "target": "大事"},
                {"emoji": "🐢", "placement": "before_phrase", "target": "言葉"},
                {"emoji": "🙏", "placement": "before_phrase", "target": "今"},
                {"emoji": "😮", "placement": "before_phrase", "target": "伝える"},
                {"emoji": "🤭", "placement": "line_end", "target": ""},
            ],
            enabled=True,
        )
        self.assertEqual(text, "😊😰大事な🐢言葉を、🙏今😮伝える。🤭")

    def test_annotations_limit_identical_text_effect_to_three_and_tail_event_to_one(self) -> None:
        text = apply_emoji_annotations(
            "本当にうれしい。",
            [
                *[{"emoji": "😊", "placement": "before_phrase", "target": "うれしい"}] * 4,
                *[{"emoji": "🤭", "placement": "line_end", "target": ""}] * 2,
            ],
            enabled=True,
        )
        self.assertEqual(text, "本当に😊😊😊うれしい。🤭")

    def test_ok_and_tender_effects_support_start_phrase_and_end_scope(self) -> None:
        text = apply_emoji_annotations(
            "大丈夫、そばにいるよ。",
            [
                {"emoji": "👌", "placement": "line_start", "target": ""},
                {"emoji": "🫶", "placement": "before_phrase", "target": "そばに"},
                {"emoji": "🫶", "placement": "line_end", "target": ""},
            ],
            enabled=True,
        )
        self.assertEqual(text, "👌大丈夫、🫶そばにいるよ。🫶")

    def test_performance_rejects_a_one_character_japanese_typo_correction(self) -> None:
        dialogue = {
            "lines": [{"line_id": "C001L001", "character_id": "cast-a", "text": "サウマで休もう。"}],
        }
        valid = {
            "performances": {
                "C001L001": {
                    "performed_text": "😊サウナで休もう。",
                    "stage_direction": "安心させるように",
                    "speech_rate": "0.98",
                }
            },
            "transitions": {"C001L001->END": {"gap_seconds": "1.2"}},
        }
        accepted, invalid_lines, invalid_transitions, corrections = assemble_draft_performance(
            dialogue,
            valid,
            lookahead_lines=[],
        )
        self.assertEqual((invalid_lines, invalid_transitions), ([], []))
        self.assertEqual(corrections, 0)
        self.assertEqual(accepted[0]["text"], "サウマで休もう。")
        self.assertEqual(accepted[0]["speechRate"], 0.98)
        self.assertEqual(accepted[0]["gapSeconds"], 1.2)

    def test_performance_falls_back_to_source_for_unapproved_text_changes(self) -> None:
        cases = [
            ("サウマで休もう。", "😊サウマで休もう", "punctuation"),
            ("えっと、サウマで休もう。", "😊サウナで休もう。", "filler removal"),
            ("サウマで休もう。", "😊サウナでゆっくり休もう。", "addition"),
            ("サウマで温かい部屋。", "😊サウナで冷たい部屋。", "multiple changes"),
            ("今日のサウマ。", "😊明日のサウナ。", "three glyph replacement"),
            ("第1話のサウマ。", "😊第2話のサウナ。", "numeral"),
            ("サウマ です。", "😊サウナです。", "whitespace"),
        ]
        for source_text, performed_text, label in cases:
            with self.subTest(label=label):
                dialogue = {
                    "lines": [
                        {
                            "line_id": "C001L001",
                            "character_id": "cast-a",
                            "text": source_text,
                        }
                    ]
                }
                directed = {
                    "performances": {
                        "C001L001": {
                            "performed_text": performed_text,
                            "stage_direction": "自然に話す",
                            "speech_rate": "1.0",
                        }
                    },
                    "transitions": {"C001L001->END": {"gap_seconds": "0.7"}},
                }
                accepted, invalid_lines, invalid_transitions, corrections = assemble_draft_performance(
                    dialogue,
                    directed,
                    lookahead_lines=[],
                )
                self.assertEqual((invalid_lines, invalid_transitions), ([], []))
                self.assertEqual(corrections, 0)
                self.assertEqual(accepted[0]["text"], source_text)

    def test_performance_retries_invalid_nontext_fields(self) -> None:
        dialogue = {
            "lines": [
                {
                    "line_id": "C001L001",
                    "character_id": "cast-a",
                    "text": "サウマで休もう。",
                }
            ]
        }
        cases = [
            ("empty direction", "😊サウナで休もう。", "", "0.98", "1.2", ["C001L001"], []),
            ("invalid rate", "😊サウナで休もう。", "自然に話す", "1.50", "1.2", ["C001L001"], []),
            ("invalid gap", "😊サウナで休もう。", "自然に話す", "0.98", "-0.1", [], ["C001L001->END"]),
        ]
        for label, performed_text, direction, speech_rate, gap, expected_lines, expected_edges in cases:
            with self.subTest(label=label):
                invalid = {
                    "performances": {
                        "C001L001": {
                            "performed_text": performed_text,
                            "stage_direction": direction,
                            "speech_rate": speech_rate,
                        }
                    },
                    "transitions": {"C001L001->END": {"gap_seconds": gap}},
                }
                _, invalid_lines, invalid_transitions, corrections = assemble_draft_performance(
                    dialogue,
                    invalid,
                    lookahead_lines=[],
                )
                self.assertEqual(invalid_lines, expected_lines)
                self.assertEqual(invalid_transitions, expected_edges)
                self.assertEqual(corrections, 0)

    def test_performance_removes_unsupported_emoji_without_retrying_valid_acting(self) -> None:
        dialogue = {
            "lines": [
                {
                    "line_id": "C001L001",
                    "character_id": "cast-a",
                    "text": "サウナで休もう。",
                }
            ]
        }
        directed = {
            "performances": {
                "C001L001": {
                    "performed_text": "☁️😋😊サウナで休もう。☔🤫",
                    "stage_direction": "安心させるように自然に話す",
                    "speech_rate": "0.98",
                }
            },
            "transitions": {"C001L001->END": {"gap_seconds": "1.2"}},
        }
        accepted, invalid_lines, invalid_transitions, corrections = assemble_draft_performance(
            dialogue,
            directed,
            lookahead_lines=[],
        )
        self.assertEqual((invalid_lines, invalid_transitions, corrections), ([], [], 0))
        self.assertEqual(accepted[0]["text"], "😊サウナで休もう。")

    def test_inner_monologue_does_not_get_automatic_echo(self) -> None:
        dialogue = {
            "lines": [
                {
                    "line_id": "C001L001",
                    "character_id": "cast-c",
                    "text": "（この問題、難しすぎます……）",
                }
            ],
        }
        directed = {
            "performances": {
                "C001L001": {
                    "performed_text": "🤔（この問題、難しすぎます……）",
                    "stage_direction": "心の中で困惑して",
                    "speech_rate": "0.90",
                }
            },
            "transitions": {"C001L001->END": {"gap_seconds": "0.8"}},
        }
        accepted, invalid_lines, invalid_transitions, corrections = assemble_draft_performance(
            dialogue,
            directed,
            lookahead_lines=[],
        )
        self.assertEqual((invalid_lines, invalid_transitions), ([], []))
        self.assertEqual(corrections, 0)
        self.assertEqual(accepted[0]["text"], "🤔（この問題、難しすぎます……）")

    def test_parenthetical_delivery_note_is_not_treated_as_inner_monologue(self) -> None:
        dialogue = {
            "lines": [
                {
                    "line_id": "C001L001",
                    "character_id": "cast-c",
                    "text": "（小声で）答えは四十二です。",
                }
            ],
        }
        directed = {
            "performances": {
                "C001L001": {
                    "performed_text": "👂（小声で）答えは四十二です。",
                    "stage_direction": "隣へ小声で伝える",
                    "speech_rate": "0.90",
                }
            },
            "transitions": {"C001L001->END": {"gap_seconds": "0.5"}},
        }
        accepted, invalid_lines, invalid_transitions, corrections = assemble_draft_performance(
            dialogue,
            directed,
            lookahead_lines=[],
        )
        self.assertEqual((invalid_lines, invalid_transitions), ([], []))
        self.assertEqual(corrections, 0)
        self.assertEqual(accepted[0]["text"], "👂（小声で）答えは四十二です。")

    def test_nonconsecutive_dramatic_silence_has_no_global_occurrence_cap(self) -> None:
        dialogue = {
            "lines": [
                {"line_id": "L1", "character_id": "cast-b", "text": "……。"},
                {"line_id": "L2", "character_id": "cast-a", "text": "まだ考えています。"},
                {"line_id": "L3", "character_id": "cast-b", "text": "……。"},
            ]
        }
        filtered, discarded = remove_repeated_draft_dialogue(
            dialogue,
            ["……。", "途中の台詞です。", "……。", "別の台詞です。", "……。", "……。"],
        )
        self.assertEqual(discarded, 0)
        self.assertEqual(
            [line["text"] for line in filtered["lines"]],
            ["……。", "まだ考えています。", "……。"],
        )

    def test_repeated_text_is_kept_for_distinct_members_of_one_integrated_cue(self) -> None:
        cue = {"cue": "SIM:S1"}
        dialogue = {"lines": [
            {"character_id": "cast-a", "text": "ありがとうございましたー！！", "integrated_direction": cue},
            {"character_id": "cast-b", "text": "ありがとうございましたー！！", "integrated_direction": cue},
        ]}
        filtered, discarded = remove_repeated_draft_dialogue(dialogue, [])
        self.assertEqual(discarded, 0)
        self.assertEqual(len(filtered["lines"]), 2)

    def test_repeated_dialogue_block_removes_only_the_later_copy(self) -> None:
        original = [
            {"character_id": "cast-a", "text": "ぼくはこのカフェの看板犬なんだよ。"},
            {"character_id": "cast-b", "text": "どうして看板犬になったの？"},
            {"character_id": "cast-a", "text": "このテラスが好きだからだよ。"},
        ]
        dialogue = {"lines": [*original, {"character_id": "cast-b", "text": "じゃあ、日向ぼっこしよう。"}, *original]}
        filtered, discarded = remove_repeated_draft_blocks(dialogue, [])
        self.assertEqual(discarded, 3)
        self.assertEqual(
            [line["text"] for line in filtered["lines"]],
            [line["text"] for line in dialogue["lines"][:4]],
        )

    def test_short_acknowledgement_block_is_not_removed(self) -> None:
        dialogue = {"lines": [
            {"character_id": "cast-a", "text": "うん。"},
            {"character_id": "cast-b", "text": "は？"},
            {"character_id": "cast-a", "text": "うん。"},
            {"character_id": "cast-a", "text": "うん。"},
            {"character_id": "cast-b", "text": "は？"},
            {"character_id": "cast-a", "text": "うん。"},
        ]}
        filtered, discarded = remove_repeated_draft_blocks(dialogue, [])
        self.assertEqual(discarded, 0)
        self.assertEqual(filtered, dialogue)

    def test_dialogue_ids_are_resequenced_after_filtering(self) -> None:
        dialogue = {
            "lines": [
                {"line_id": "C001L001", "character_id": "cast-a", "text": "一行目。"},
                {"line_id": "C001L003", "character_id": "cast-b", "text": "三行目だった台詞。"},
            ]
        }
        resequence_draft_dialogue(dialogue, 0)
        self.assertEqual(
            [line["line_id"] for line in dialogue["lines"]],
            ["C001L001", "C001L002"],
        )

    def test_duration_uses_authored_rate_and_gap(self) -> None:
        scenes = [
            {
                "lines": [
                    {
                        "text": "あ" * 11,
                        "speechRate": 1.0,
                        "gapSeconds": 1.5,
                    }
                ]
            }
        ]
        self.assertEqual(estimated_draft_seconds(scenes), 2.0)

    def test_duration_tolerates_blank_fallback_gap(self) -> None:
        scenes = [{"lines": [{"text": "あ" * 11, "speechRate": "", "gapSeconds": ""}]}]
        self.assertEqual(estimated_draft_seconds(scenes), 2.0)

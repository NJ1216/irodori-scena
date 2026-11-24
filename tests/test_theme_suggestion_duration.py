from __future__ import annotations

import unittest

from pydantic import ValidationError

from server.app import AiJobRequest, DraftRequest, ThemeSuggestionRequest
from server.modules.suggestions import theme_suggestion_guidance
from server.modules.draft_theme import draft_outline_policy


class ThemeSuggestionDurationTests(unittest.TestCase):
    def test_guidance_scales_with_duration(self) -> None:
        expectations = {
            1: ("180〜260文字", "一つの状況", 646),
            3: ("250〜350文字", "一つの状況", 781),
            10: ("400〜600文字", "数段階の進展", 1156),
            30: ("900〜1300文字", "伏線", 2206),
            60: ("1600〜2200文字", "複数幕相当", 3556),
        }
        for minutes, expected in expectations.items():
            with self.subTest(minutes=minutes):
                length_target, structure, max_tokens = theme_suggestion_guidance(minutes, 0)
                self.assertEqual((length_target, max_tokens), (expected[0], expected[2]))
                self.assertIn(expected[1], structure)

    def test_defaults_to_three_minutes_and_preserves_long_input_budget(self) -> None:
        request = ThemeSuggestionRequest(character_ids=["cast-a"])
        self.assertEqual(request.target_minutes, 3)
        self.assertEqual(theme_suggestion_guidance(3, 4000)[2], 4096)
        with self.assertRaises(ValidationError):
            ThemeSuggestionRequest(character_ids=["cast-a"], target_minutes=61)

    def test_outline_policy_covers_duration_and_theme_density(self) -> None:
        cases = (
            (3, "短いテーマ。", "expand", 1),
            (3, "短い尺の長いテーマ。" * 40, "compress", 1),
            (30, "短いテーマ。", "expand", 8),
            (30, "長尺に適した十分なテーマ。" * 80, "preserve", 8),
        )
        for minutes, theme, mode, chapters in cases:
            with self.subTest(minutes=minutes, mode=mode):
                policy = draft_outline_policy(minutes, theme)
                self.assertEqual((policy["mode"], policy["story_chapters"]), (mode, chapters))

    def test_ai_draft_contracts_allow_eight_casts_and_reject_nine(self) -> None:
        eight = [f"cast-{index}" for index in range(8)]
        nine = [*eight, "cast-8"]
        self.assertEqual(len(DraftRequest(character_ids=eight, target_minutes=3,
                                          theme="8人で進むテスト台本です。").character_ids), 8)
        self.assertEqual(len(ThemeSuggestionRequest(character_ids=eight).character_ids), 8)
        self.assertEqual(len(AiJobRequest(mode="draft", character_ids=eight, target_minutes=3,
                                          theme="8人で進むテスト台本です。").character_ids), 8)
        for model, kwargs in (
            (DraftRequest, {"target_minutes": 3, "theme": "9人は拒否するテストです。"}),
            (ThemeSuggestionRequest, {}),
            (AiJobRequest, {"mode": "draft", "target_minutes": 3, "theme": "9人は拒否するテストです。"}),
        ):
            with self.subTest(model=model.__name__), self.assertRaises(ValidationError):
                model(character_ids=nine, **kwargs)


if __name__ == "__main__":
    unittest.main()

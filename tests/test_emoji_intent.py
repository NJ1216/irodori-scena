from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest

from server.modules.constants import (
    AI_PROPOSABLE_EMOJIS,
    EMOJI_PERFORMANCE_RULEBOOK,
    IRODORI_EMOJIS,
    emoji_annotation_schema,
    enforce_tutting_intent,
)
from server.modules.direction_fields import ai_allowed_emojis, ai_reverb_explicitly_requested
from server.modules.models import AiDirectionRequest, DraftRequest, LineAssistantRequest, VoiceDesignSuggestionRequest


class EmojiIntentTests(unittest.TestCase):
    def test_keeps_tutting_when_stage_direction_names_the_sound(self) -> None:
        self.assertEqual(enforce_tutting_intent("もういい😒", "発話後に小さく舌打ちする"), "もういい😒")

    def test_removes_tutting_used_as_general_displeasure(self) -> None:
        self.assertEqual(enforce_tutting_intent("もういい😒", "不満げに呆れて言う"), "もういい")

    def test_rulebook_distinguishes_similar_effects_and_placement(self) -> None:
        self.assertIn("😮は実際に息をのむ音、😲は驚いた話し方", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("文中の間や⏸️の代用にしない", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("非言語音の長さ・回数・音量が比例して増えるとは仮定しない", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("同じ演技意図を複数のplacementへ重複させない", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("🤔・👌・🫶は配置で効果範囲を使い分け", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("line_startは発話冒頭から行全体", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("before_phraseは対象の一単語・最短語句だけ", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("line_endは文全体の語尾へ効かせる", EMOJI_PERFORMANCE_RULEBOOK)
        self.assertIn("発話末尾へ効かせるline_end", emoji_annotation_schema())

    def test_muffled_effect_remains_manually_supported_but_is_not_ai_proposable(self) -> None:
        self.assertIn("🤐", IRODORI_EMOJIS)
        self.assertNotIn("🤐", AI_PROPOSABLE_EMOJIS)
        self.assertNotIn("🤐=口を塞ぐ", emoji_annotation_schema())

    def test_ai_reverb_requires_affirmative_request_local_author_text(self) -> None:
        draft = DraftRequest(character_ids=["cast-a"], target_minutes=1, theme="廃虚で大声を出す場面です。")
        explicit = DraftRequest(character_ids=["cast-a"], target_minutes=1, theme="台詞へ強いリバーブをかける。")
        negative = DraftRequest(character_ids=["cast-a"], target_minutes=1, theme="残響を使わない静かな場面です。")
        self.assertNotIn("📢", ai_allowed_emojis(draft, {"📢", "😊"}))
        self.assertEqual(ai_allowed_emojis(explicit, {"📢", "😊"}), {"📢", "😊"})
        self.assertFalse(ai_reverb_explicitly_requested(negative))

    def test_ai_reverb_policy_covers_each_authoring_request_type(self) -> None:
        line = LineAssistantRequest(
            scene_id="scene", character_id="cast", instruction="この一行だけエコーをかける",
        )
        voice = VoiceDesignSuggestionRequest(keywords="残響を強くかけた神秘的な声")
        direction = AiDirectionRequest(line_ids=["line"], allowed_emojis=["📢", "😊"])
        self.assertIn("📢", ai_allowed_emojis(line, {"📢"}))
        self.assertIn("📢", ai_allowed_emojis(voice, {"📢"}))
        self.assertEqual(ai_allowed_emojis(direction, direction.allowed_emojis), {"😊"})


if __name__ == "__main__":
    unittest.main()

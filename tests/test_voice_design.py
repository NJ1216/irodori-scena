import scena_test_isolation  # noqa: F401
import unittest

from server.modules.voice_design import (
    VOICE_DESIGN_AUDIO_QUALITY_SUFFIX,
    VOICE_DESIGN_OPTIONS,
    VoiceDesignModel,
    inference_caption,
    voice_design_keywords,
)


class VoiceDesignTests(unittest.TestCase):
    def test_age_and_gender_options_match_the_effective_prompt_terms(self) -> None:
        self.assertNotIn("幼児", VOICE_DESIGN_OPTIONS["AGE"])
        self.assertNotIn("幼稚園児", VOICE_DESIGN_OPTIONS["AGE"])
        self.assertEqual(VOICE_DESIGN_OPTIONS["GENDER"], ("男児", "女児", "男の子", "女の子", "男性", "女性", "中性"))

    def test_legacy_neutral_gender_is_normalized(self) -> None:
        self.assertEqual(VoiceDesignModel(gender="中性的").gender, "中性")

    def test_unselected_fields_are_left_out_of_the_prompt(self) -> None:
        keywords = voice_design_keywords(
            {"age": None, "gender": "女児", "pitch": None, "qualities": ["甘い", None], "style": None, "notes": None}
        )
        self.assertEqual(keywords, "女児の声。甘い声質。")

    def test_structured_prompt_order_and_suffix(self) -> None:
        keywords = voice_design_keywords(
            {
                "age": "小学校低学年",
                "gender": "男性",
                "pitch": "やや高い",
                "qualities": ["ハスキー", "太い", "胸に響く"],
                "style": "威厳のある",
                "notes": "語尾は短く。",
            }
        )
        self.assertEqual(
            keywords,
            "小学校低学年の声。男性の声。やや高い声。ハスキーな声質。太い声質。胸に響く声質。威厳のある話し方。語尾は短く。",
        )
        self.assertEqual(inference_caption(keywords), f"{keywords}{VOICE_DESIGN_AUDIO_QUALITY_SUFFIX}")

    def test_quality_suffix_is_appended_exactly_once(self) -> None:
        value = f"低い声。{VOICE_DESIGN_AUDIO_QUALITY_SUFFIX}"
        self.assertEqual(inference_caption(value), value)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server.app import ImagePromptSuggestionRequest
from server.modules.image_prompt_suggestions import (
    EXPRESSIONS,
    EXPRESSION_TAGS,
    TAG_VALUES,
    build_image_prompt,
    convert_custom_fields,
    custom_fields,
    parse_custom_tags,
    suggest_character_image_prompt,
)


class ImagePromptSuggestionTests(unittest.TestCase):
    def test_anime_hairstyle_presets_have_deterministic_tags(self) -> None:
        expected = {
            "アシンメトリー": "asymmetrical hair", "姫カット": "hime cut", "サイドカット": "sidecut",
            "ピクシーカット": "pixie cut", "スパイクヘア": "spiked hair", "モヒカン": "mohawk",
            "ローポニーテール": "low ponytail", "ハイポニーテール": "high ponytail",
            "サイドポニーテール": "side ponytail", "ショートポニーテール": "short ponytail",
            "低いツインテール": "low twintails", "ハーフアップツインテール": "half up twintails",
            "片側三つ編み": "side braid", "ツインブレイド": "twin braids", "ドリルヘア": "drill hair",
            "縦ロール": "ringlets", "髪を下ろす": "hair down",
        }
        self.assertEqual({name: TAG_VALUES["hairstyle"][name] for name in expected}, expected)

    def test_expression_presets_have_five_groups_of_fifteen_without_generic_entries(self) -> None:
        self.assertEqual(len(EXPRESSIONS), 75)
        self.assertEqual(len(EXPRESSION_TAGS), 75)
        self.assertTrue({"真顔", "嬉しい", "笑い", "悲しい", "怒り"}.isdisjoint(EXPRESSIONS))
        self.assertEqual(len(set(EXPRESSIONS)), 75)

    def request(self, **changes: object) -> ImagePromptSuggestionRequest:
        values = {
            "subject": "女性キャラクター",
            "style": "アニメ調",
            "composition": "バストアップ",
            "age_impression": "若い成人",
            "body_build": "細身",
            "skin_tone": "明るめ",
            "face_contour": "卵型",
            "hair_length": "ショルダーレングス",
            "hairstyle": "カールヘア",
            "hair_texture": "ゆるいウェーブ",
            "hair_color": "navy blue",
            "secondary_hair_color_enabled": True,
            "secondary_hair_color": "pink",
            "secondary_hair_color_style": "インナーカラー",
            "eye_color": "sky blue",
            "eye_style": "たれ目",
            "expression": "穏やかな微笑み",
            "outfit": "ブレザー制服",
            "outfit_impression": "上品系",
            "accessory": "なし",
            "background": "なし",
        }
        values.update(changes)
        return ImagePromptSuggestionRequest(**values)

    def test_builds_presets_in_fixed_order_without_llm(self) -> None:
        result = build_image_prompt(self.request())
        self.assertEqual(
            result["imagePrompt"],
            "1girl, solo, anime style, upper body, young adult, slender, fair skin, oval face, "
            "shoulder-length hair, curly hair, slightly wavy hair, navy blue hair, pink hair, colored inner hair, "
            "sky blue eyes, tareme, gentle smile, school blazer, elegant outfit, simple background, white background",
        )
        self.assertFalse(result["usedLlm"])
        self.assertEqual(result["ignoredCustomFields"], [])

    def test_subject_presets_and_new_hairstyles(self) -> None:
        expected = {
            "女性キャラクター": "1girl, solo",
            "男性キャラクター": "1boy, solo",
            "中性的・その他": "1other, solo",
            "限定しない": "1person, solo",
            "": "1person, solo",
        }
        for subject, prefix in expected.items():
            result = build_image_prompt(self.request(subject=subject, hairstyle="ヘアフラップ"))
            self.assertTrue(result["imagePrompt"].startswith(prefix))
            self.assertIn("hair flaps", result["imagePrompt"])

    def test_deduplicates_and_omits_none_tags(self) -> None:
        result = build_image_prompt(self.request(hairstyle="ストレート", hair_texture="ストレート", accessory="なし"))
        self.assertEqual(result["imagePrompt"].count("straight hair"), 1)
        self.assertNotIn("no accessory", result["imagePrompt"])

    def test_only_custom_values_are_selected_for_llm(self) -> None:
        fields = custom_fields(self.request(subject="リザードマン", hair_color="#173B6D", height="167cm", request="紺色のコート"))
        self.assertEqual(fields, {"subject": "リザードマン", "height": "167cm", "hair_color": "#173B6D", "request": "紺色のコート"})

    def test_partial_and_truncated_json_preserves_valid_siblings(self) -> None:
        parsed = parse_custom_tags(
            '{"height":{"category":"body","tags":"tall"},'
            '"hair_color":{"category":"hair","tags":"navy hair 😊"},'
            '"unknown":{"category":"hair","tags":"bad"},'
            '"request":{"category":"outfit","tags":"navy coat"',
            {"height", "hair_color", "request"},
        )
        self.assertEqual(parsed["height"], ("body", ["tall"]))
        self.assertEqual(parsed["hair_color"], ("hair", ["navy hair"]))
        self.assertNotIn("request", parsed)
        self.assertNotIn("unknown", parsed)

    def test_supported_response_wrappers_have_the_same_result(self) -> None:
        expected = {"accessory": ("outfit", ["tiara"])}
        for response in (
            '{"records":[{"field":"accessory","category":"outfit","tags":["tiara"]}]}',
            '{"accessory":{"category":"outfit","tags":"tiara"}}',
            '{"custom_fields":{"accessory":{"category":"outfit","tags":"tiara"}}}',
        ):
            self.assertEqual(parse_custom_tags(response, {"accessory"}), expected)

    def test_invalid_fields_do_not_discard_valid_truncated_siblings(self) -> None:
        parsed = parse_custom_tags(
            '{"custom_fields":{"accessory":{"category":"outfit","tags":"tiara (annotation), 😊"},'
            '"hairstyle":{"category":"body","tags":"long hair"},'
            '"outfit":{"category":"outfit","tags":[]},'
            '"unknown":{"category":"hair","tags":"bad"},'
            '"background":{"category":"background","tags":"starry sky"',
            {"accessory", "hairstyle", "outfit", "background"},
        )
        self.assertEqual(parsed, {
            "accessory": ("outfit", ["tiara"]),
            "hairstyle": ("hair", ["long hair"]),
        })

    def test_endpoint_skips_llm_for_presets_even_without_model(self) -> None:
        with patch("server.modules.llm_client.openai_text_completion") as completion:
            result = suggest_character_image_prompt(self.request())
        completion.assert_not_called()
        self.assertFalse(result["usedLlm"])

    def test_pose_gestures_camera_composition_and_background_are_deterministic(self) -> None:
        request = self.request(
            composition="膝上まで写す", camera_angle="下から見上げる", screen_effect="動きをぼかす", pose="ジャンプ",
            gestures=["両手でピース", "サムズアップ"], background="夜景",
        )
        with patch("server.modules.llm_client.openai_text_completion") as completion:
            result = suggest_character_image_prompt(request)
        completion.assert_not_called()
        prompt = result["imagePrompt"]
        self.assertLess(prompt.index("cowboy shot"), prompt.index("from below"))
        self.assertLess(prompt.index("from below"), prompt.index("motion blur"))
        self.assertLess(prompt.index("motion blur"), prompt.index("young adult"))
        self.assertLess(prompt.index("elegant outfit"), prompt.index("jumping"))
        self.assertLess(prompt.index("jumping"), prompt.index("double peace"))
        self.assertTrue(prompt.endswith("night cityscape"))

    def test_all_new_fixed_options_have_tags(self) -> None:
        expected_counts = {
            "pose": 10, "composition": 27, "camera_angle": 20, "screen_effect": 19, "background": 20,
            "age_impression": 33, "occupation": 114, "expression": 75, "accessory": 77,
        }
        for field, count in expected_counts.items():
            self.assertEqual(len(TAG_VALUES[field]), count)
        self.assertTrue(all(TAG_VALUES["occupation"].values()))
        self.assertTrue(all(TAG_VALUES["expression"].values()))
        self.assertTrue(all(TAG_VALUES["screen_effect"].values()))
        self.assertTrue(all(tag for name, tag in TAG_VALUES["accessory"].items() if name != "なし"))

    def test_old_background_values_remain_compatible(self) -> None:
        self.assertTrue(build_image_prompt(self.request(background="なし"))["imagePrompt"].endswith("simple background, white background"))
        self.assertTrue(build_image_prompt(self.request(background="あり"))["imagePrompt"].endswith("background"))

    def test_height_age_and_background_color_presets_skip_llm(self) -> None:
        request = self.request(
            height="165cm", age_impression="高校生", background="グラデーション",
            background_gradient_color1="red", background_gradient_color2="blue",
            background_gradient_direction="左上から右下",
        )
        with patch("server.modules.llm_client.openai_text_completion") as completion:
            result = suggest_character_image_prompt(request)
        completion.assert_not_called()
        self.assertIn("165cm", result["imagePrompt"])
        self.assertIn("15-17 years old", result["imagePrompt"])
        self.assertTrue(result["imagePrompt"].endswith("gradient background, red, blue, diagonal gradient"))

    def test_numeric_age_occupation_and_multiple_features_use_fixed_tags(self) -> None:
        request = self.request(
            age_impression="6~8才", occupation="警察官", makeup="華やか",
            freckles_moles="薄いそばかす, 左目の下のほくろ",
            facial_hair="口ひげ, あごひげ", scars="眉の傷, 腕の傷",
            tattoos="肩のタトゥー, 足首のタトゥー", accessory="ティアラ, 王冠",
        )
        with patch("server.modules.llm_client.openai_text_completion") as completion:
            result = suggest_character_image_prompt(request)
        completion.assert_not_called()
        prompt = result["imagePrompt"]
        for tag in ("6-8 years old", "police officer", "light freckles", "mole under left eye", "mustache", "goatee", "eyebrow scar", "arm scar", "shoulder tattoo", "ankle tattoo", "tiara", "crown"):
            self.assertIn(tag, prompt)
        self.assertNotIn("makeup", prompt)

    def test_llm_failure_keeps_deterministic_prompt_and_reports_ignored_fields(self) -> None:
        request = self.request(height="167cm")
        with patch("server.modules.llm_client.openai_text_completion", side_effect=RuntimeError("offline")):
            result = suggest_character_image_prompt(request)
        self.assertTrue(result["imagePrompt"].startswith("1girl, solo"))
        self.assertEqual(result["ignoredCustomFields"], ["height"])
        self.assertTrue(result["warnings"])

    def test_partial_llm_result_merges_at_semantic_positions(self) -> None:
        request = self.request(height="167cm", request="夜の街")
        response = '{"height":{"category":"body","tags":"tall"},"request":{"category":"background","tags":"city at night"}}'
        with patch("server.modules.llm_client.openai_text_completion", return_value=response):
            result = suggest_character_image_prompt(request)
        self.assertLess(result["imagePrompt"].index("tall"), result["imagePrompt"].index("curly hair"))
        self.assertTrue(result["imagePrompt"].endswith("city at night"))
        self.assertEqual(result["ignoredCustomFields"], [])

    def test_custom_fields_wrapper_converts_accessory_without_warning(self) -> None:
        request = self.request(accessory="ティアラ")
        response = '{"custom_fields":{"accessory":{"category":"outfit","tags":"tiara"}}}'
        with patch("server.modules.llm_client.openai_text_completion", return_value=response):
            result = suggest_character_image_prompt(request)
        self.assertIn("tiara", result["imagePrompt"])
        self.assertLess(result["imagePrompt"].index("elegant outfit"), result["imagePrompt"].index("tiara"))
        self.assertEqual(result["ignoredCustomFields"], [])
        self.assertEqual(result["warnings"], [])

    def test_occupation_translation_survives_model_category_mismatch(self) -> None:
        request = self.request(
            occupation="魔王", outfit_impression="装飾品の付いた漆黒のローブ",
            background="魔王城", request="威厳に満ち溢れた",
        )
        response = (
            '```json\n{"records":['
            '{"field":"occupation","category":"subject","tags":"demon lord"},'
            '{"field":"outfit_impression","category":"outfit","tags":["black robe","ornate"]},'
            '{"field":"background","category":"background","tags":"demon lord\'s castle"},'
            '{"field":"request","category":"style","tags":"majestic"}'
            ']}\n```'
        )
        with patch("server.modules.llm_client.openai_text_completion", return_value=response):
            result = suggest_character_image_prompt(request)
        self.assertIn("demon lord", result["imagePrompt"])
        self.assertIn("black robe", result["imagePrompt"])
        self.assertIn("demon lord's castle", result["imagePrompt"])
        self.assertIn("majestic", result["imagePrompt"])
        self.assertEqual(result["ignoredCustomFields"], [])
        self.assertEqual(parse_custom_tags('{"records":[{"field":"occupation","tags":"demon lord"}]}', {"occupation"}),
                         {"occupation": ("outfit", ["demon lord"])})

    def test_structured_records_use_known_field_destinations(self) -> None:
        records = SimpleNamespace(records=[
            {"field": "occupation", "category": "subject", "tags": "demon lord"},
            {"field": "outfit_impression", "tags": ["black robe"]},
            {"field": "request", "category": "invalid", "tags": "majestic"},
        ])
        request = self.request(occupation="魔王", outfit_impression="漆黒のローブ", request="威厳")
        with patch("server.modules.llm_completion_service.complete_records", return_value=records):
            converted = convert_custom_fields(request, custom_fields(request))
        self.assertEqual(converted, {
            "occupation": ("outfit", ["demon lord"]),
            "outfit_impression": ("outfit", ["black robe"]),
        })

    def test_multiple_custom_fields_merge_into_their_groups(self) -> None:
        request = self.request(hairstyle="姫ロング", outfit="軍服", background="星空")
        response = (
            '{"records":['
            '{"field":"hairstyle","category":"hair","tags":"long hime cut"},'
            '{"field":"outfit","category":"outfit","tags":["military uniform"]},'
            '{"field":"background","category":"background","tags":"starry sky"}'
            ']}'
        )
        with patch("server.modules.llm_client.openai_text_completion", return_value=response):
            result = suggest_character_image_prompt(request)
        prompt = result["imagePrompt"]
        self.assertLess(prompt.index("long hime cut"), prompt.index("sky blue eyes"))
        self.assertLess(prompt.index("military uniform"), prompt.index("starry sky"))
        self.assertEqual(result["ignoredCustomFields"], [])


if __name__ == "__main__":
    unittest.main()

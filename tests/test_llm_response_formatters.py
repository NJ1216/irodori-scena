from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import parse_generated_lines, parse_profile_suggestion
from server.modules.llm_response_formatters import parse_voice_design
from server.modules.models import CharacterProfileSuggestionRequest, VoiceDesignSuggestionRequest
from server.modules.profile_suggestions import suggest_character_profile_completion
from server.modules.suggestions import is_japanese_voice_design_caption, suggest_voice_design_completion


class LlmResponseFormatterTests(unittest.TestCase):
    def test_negative_tts_caption_is_rejected_without_losing_valid_siblings(self) -> None:
        parsed = parse_voice_design("VOICE_KEYWORDS|柔らかい声。エコーを使わない。\nBASELINE_TEXT|今日は一緒に歩こう。")
        self.assertEqual(parsed, {"BASELINE_TEXT": "今日は一緒に歩こう。"})

        lines = parse_generated_lines(
            "LINE|大丈夫だよ。|反響させずに優しく|0.95|0.4|NONE\nLINE|忘れられないね。|切ない声で|0.90|0.6|NONE"
        )
        self.assertEqual(lines[0]["stage_direction"], "")
        self.assertEqual(lines[0]["text"], "大丈夫だよ。")
        self.assertEqual(lines[1]["stage_direction"], "切ない声で")

    def test_voice_design_json_drops_unknown_keys_and_keeps_known_ones(self) -> None:
        parsed = parse_voice_design('{"VOICE_KEYWORDS":"柔らかい声。","BASELINE_TEXT":"今日は歩こう。","extra":"z"}')
        self.assertEqual(parsed, {"VOICE_KEYWORDS": "柔らかい声。", "BASELINE_TEXT": "今日は歩こう。"})

    def test_voice_design_caption_allows_common_latin_terms_but_rejects_english_led_text(self) -> None:
        self.assertTrue(is_japanese_voice_design_caption("ASMR向けの近距離で柔らかなVTuber風の声。"))
        self.assertTrue(is_japanese_voice_design_caption("YouTubeの配信で明るく話す。"))
        self.assertFalse(is_japanese_voice_design_caption("calm warm female voice"))
        self.assertFalse(is_japanese_voice_design_caption("calm warm female voiceで話す"))

    def test_voice_design_suggestion_requires_japanese_tts_captions(self) -> None:
        request = VoiceDesignSuggestionRequest(
            base_url="http://127.0.0.1:11434/v1",
            model="test-model",
            keywords="穏やかな大人の女性",
        )
        response = "\n".join(
            (
                "AGE|20代",
                "GENDER|女性",
                "PITCH|低い",
                "QUALITY|透明感のある、太い",
                "STYLE|穏やか",
                "NOTES|語尾はやわらかく",
                "BASELINE_TEXT|こんにちは。今日は穏やかにお話しします。",
                "NORMAL_TEXT|今日は😊いつもどおり、落ち着いて進めましょう。",
                "JOY_TEXT|わあ、📢😊とても嬉しいです！",
                "ANGER_TEXT|それは、😠見過ごせません。",
                "SORROW_TEXT|少しだけ、😢寂しくなりました。",
                "DELIGHT_TEXT|やった、🥰素敵ですね。",
            )
        )
        captured: dict[str, object] = {}

        def completion(*_args, **kwargs):
            captured.update(kwargs)
            return response

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/voice-design-suggestion")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
        ):
            result = suggest_voice_design_completion(request)

        self.assertEqual(
            result["voiceDesign"],
            {
                "age": "20代",
                "gender": "女性",
                "pitch": "低い",
                "qualities": ["透明感のある", "太い"],
                "style": "穏やか",
                "notes": "語尾はやわらかく",
            },
        )
        self.assertEqual(result["emotionTexts"]["normal"], "今日はいつもどおり、落ち着いて進めましょう。")
        self.assertEqual(result["emotionTexts"]["joy"], "わあ、😊とても嬉しいです！")
        self.assertIn("BASELINE_TEXT", captured["system"])
        self.assertIn("約60文字", captured["system"])
        self.assertIn("NORMAL_TEXTにはEMOJIを入れません", captured["system"])
        self.assertIn("固定選択肢", captured["system"])

    def test_voice_design_suggestion_keeps_valid_partial_rows_and_filters_forbidden_emoji_loop(self) -> None:
        request = VoiceDesignSuggestionRequest(
            base_url="http://127.0.0.1:11434/v1",
            model="qwen3.8:27b-nvfp4",
            keywords="元気な男の子",
        )
        response = "\n".join(
            (
                "VOICE_KEYWORDS|10歳くらいの元気な男の子の声。明るく活発に話す。",
                "BASELINE_TEXT|今日はいい天気だね。一緒に公園へ遊びに行こうよ。",
                "NORMAL_TEXT|今日はいい天気だね。一緒に公園へ遊びに行こうよ。",
                f"JOY_TEXT|{'👋' * 400}",
            )
        )
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/voice-design-suggestion")),
            patch("server.modules.llm_client.openai_text_completion", return_value=response) as completion,
        ):
            result = suggest_voice_design_completion(request)
        self.assertEqual(completion.call_count, 1)
        self.assertIsNone(result["voiceDesign"])
        self.assertEqual(result["baselineText"], "今日はいい天気だね。一緒に公園へ遊びに行こうよ。")
        self.assertEqual(result["emotionTexts"], {"normal": "今日はいい天気だね。一緒に公園へ遊びに行こうよ。"})

    def test_profile_suggestion_accepts_gemma_rows_without_prefix(self) -> None:
        parsed = parse_profile_suggestion(
            "familyName|苗字|久遠／\ngivenName|名前|澪|\nFIELD|age|19歳",
            labels={"familyName": "苗字", "givenName": "名前", "age": "年齢"},
            blank_fields={"familyName", "givenName", "age"},
            allowed_relation_names=set(),
        )
        self.assertEqual(parsed, ({"familyName": "久遠", "givenName": "澪", "age": "19歳"}, {}))

    def test_profile_suggestion_expands_a_packed_field_record(self) -> None:
        labels = {
            "familyName": "苗字",
            "familyNameKana": "苗字のふりがな",
            "givenName": "名前",
            "relationships": "人間関係",
        }
        raw = (
            "FIELD|キャラクター 10|familyName|苗字|咲良|familyNameKana|さくら|"
            "givenName|名前|莉里|relationships|人間関係|人間関係|少佐と不思議な縁がある|"
            "RELATION|Riri|関係メモ|明るさで距離を縮める|"
        )

        parsed = parse_profile_suggestion(
            raw,
            labels=labels,
            blank_fields=set(labels),
            allowed_relation_names={"Riri"},
        )

        self.assertEqual(
            parsed,
            (
                {
                    "familyName": "咲良",
                    "familyNameKana": "さくら",
                    "givenName": "莉里",
                    "relationships": "少佐と不思議な縁がある",
                },
                {"Riri": {"relationship": "明るさで距離を縮める"}},
            ),
        )

    def test_profile_suggestion_discards_relations_not_from_the_edited_character(self) -> None:
        labels = {"personality": "性格"}
        raw = (
            "FIELD|性格|朗らか|RELATION|Riri|少佐|不思議な縁がある|"
            "RELATION|少佐|新規キャスト|こちらからの関係ではない|RELATION|新規キャスト|Riri|友好的"
        )

        parsed = parse_profile_suggestion(
            raw,
            labels=labels,
            blank_fields={"personality"},
            allowed_relation_names={"Riri", "少佐"},
            subject_name="新規キャスト",
        )

        self.assertEqual(parsed, ({"personality": "朗らか"}, {"Riri": {"relationship": "友好的"}}))

    def test_profile_suggestion_accepts_a_fixed_internal_field_name(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|defaultAddressBasis|親しい相手には愛称で呼ぶ",
            labels={"defaultAddressBasis": "呼び方の基準"},
            blank_fields={"defaultAddressBasis"},
            allowed_relation_names=set(),
        )

        self.assertEqual(parsed, ({"defaultAddressBasis": "親しい相手には愛称で呼ぶ"}, {}))

    def test_profile_suggestion_discards_unspecified_values(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|年齢|未設定\nFIELD|性別|女",
            labels={"age": "年齢", "gender": "性別"},
            blank_fields={"age", "gender"},
            allowed_relation_names=set(),
        )

        self.assertEqual(parsed, ({"gender": "女"}, {}))

    def test_profile_suggestion_maps_second_speech_register_to_speech_style(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|話し方|ハキハキとした口調\nFIELD|話し方|「〜だよ」と話す",
            labels={"defaultSpeechRegister": "話し方", "speechStyle": "基本の口調"},
            blank_fields={"defaultSpeechRegister", "speechStyle"},
            allowed_relation_names=set(),
        )

        self.assertEqual(
            parsed,
            ({"defaultSpeechRegister": "ハキハキとした口調", "speechStyle": "「〜だよ」と話す"}, {}),
        )

    def test_profile_suggestion_accepts_fixed_short_labels(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|背景|運動好きの高校生\nFIELD|好き嫌い|自由な時間を好む",
            labels={"background": "背景・来歴", "likesDislikes": "好きなもの・苦手なもの"},
            blank_fields={"background", "likesDislikes"},
            allowed_relation_names=set(),
        )

        self.assertEqual(parsed, ({"background": "運動好きの高校生", "likesDislikes": "自由な時間を好む"}, {}))

    def test_profile_suggestion_ignores_the_editor_controlled_display_name(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|表示名|佐倉 凛\nFIELD|年齢|17歳",
            labels={"age": "年齢"},
            blank_fields={"age"},
            allowed_relation_names=set(),
        )

        self.assertEqual(parsed, ({"age": "17歳"}, {}))

    def test_profile_suggestion_discards_an_unknown_field_and_keeps_valid_siblings(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|秘密設定|不明\nFIELD|年齢|17歳",
            labels={"age": "年齢"},
            blank_fields={"age"},
            allowed_relation_names=set(),
        )

        self.assertEqual(parsed, ({"age": "17歳"}, {}))

    def test_profile_suggestion_keeps_relations_when_all_profile_fields_are_filled(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|身長|158cm\nRELATION|紗良|憧れのお姉さん。",
            labels={"age": "年齢"},
            blank_fields=set(),
            allowed_relation_names={"紗良"},
        )

        self.assertEqual(parsed, ({}, {"紗良": {"relationship": "憧れのお姉さん。"}}))

    def test_profile_suggestion_accepts_relation_subfields_independently(self) -> None:
        parsed = parse_profile_suggestion(
            "RELATION|Riri|関係性|家がお隣で、会話では軽口を言い合う。\nRELATION|Riri|呼び方|Ririっち",
            labels={},
            blank_fields=set(),
            allowed_relation_names={"Riri"},
            allowed_relation_fields={"Riri": {"address", "relationship"}},
        )

        self.assertEqual(
            parsed, ({}, {"Riri": {"address": "Ririっち", "relationship": "家がお隣で、会話では軽口を言い合う。"}})
        )

    def test_profile_suggestion_accepts_legacy_address_and_relationship_record(self) -> None:
        parsed = parse_profile_suggestion(
            "RELATION|紗良|さーちゃん|穏やかで憧れるお姉さん。",
            labels={},
            blank_fields=set(),
            allowed_relation_names={"紗良"},
            allowed_relation_fields={"紗良": {"address", "relationship"}},
        )
        self.assertEqual(parsed, ({}, {"紗良": {"address": "さーちゃん", "relationship": "穏やかで憧れるお姉さん。"}}))

        parsed = parse_profile_suggestion(
            "RELATION|紗良|さーちゃん|穏やかで憧れるお姉さん。",
            labels={},
            blank_fields=set(),
            allowed_relation_names={"紗良"},
            allowed_relation_fields={"紗良": {"relationship"}},
        )
        self.assertEqual(parsed, ({}, {"紗良": {"relationship": "穏やかで憧れるお姉さん。"}}))

    def test_explicit_relation_field_overrides_legacy_inferred_field(self) -> None:
        parsed = parse_profile_suggestion(
            "RELATION|紗良|さーちゃん|幼なじみ。\nRELATION|紗良|関係性|幼なじみで、今は仕事上の相棒。",
            labels={},
            blank_fields=set(),
            allowed_relation_names={"紗良"},
            allowed_relation_fields={"紗良": {"address", "relationship"}},
        )
        self.assertEqual(
            parsed,
            (
                {},
                {
                    "紗良": {
                        "address": "さーちゃん",
                        "relationship": "幼なじみで、今は仕事上の相棒。",
                    }
                },
            ),
        )

    def test_same_priority_relation_conflict_rejects_only_that_field(self) -> None:
        parsed = parse_profile_suggestion(
            "RELATION|紗良|呼び方|さーちゃん\nRELATION|紗良|呼び方|紗良さん\nRELATION|紗良|関係性|幼なじみ。",
            labels={},
            blank_fields=set(),
            allowed_relation_names={"紗良"},
            allowed_relation_fields={"紗良": {"address", "relationship"}},
        )
        self.assertEqual(parsed, ({}, {"紗良": {"relationship": "幼なじみ。"}}))

    def test_profile_suggestion_json_keeps_only_blank_relation_subfields(self) -> None:
        parsed = parse_profile_suggestion(
            '{"profile_details":{},"cast_relations":{"Riri":{"address":"リリ","relationship":"幼なじみ"}}}',
            labels={},
            blank_fields=set(),
            allowed_relation_names={"Riri"},
            allowed_relation_fields={"Riri": {"address"}},
        )

        self.assertEqual(parsed, ({}, {"Riri": {"address": "リリ"}}))

    def test_profile_suggestion_accepts_unambiguous_label_variants(self) -> None:
        parsed = parse_profile_suggestion(
            "\n".join(
                [
                    "FIELD|その他への敬称|様",
                    "FIELD|口調|穏やかな敬語",
                    "FIELD|好きな物・苦手な物|読書／騒音",
                ]
            ),
            labels={
                "defaultHonorificOther": "その他・未設定への敬称",
                "speechStyle": "基本の口調",
                "likesDislikes": "好きなもの・苦手なもの",
            },
            blank_fields={"defaultHonorificOther", "speechStyle", "likesDislikes"},
            allowed_relation_names=set(),
        )

        self.assertEqual(
            parsed,
            (
                {
                    "defaultHonorificOther": "様",
                    "speechStyle": "穏やかな敬語",
                    "likesDislikes": "読書／騒音",
                },
                {},
            ),
        )

    def test_profile_suggestion_discards_name_based_pronoun_templates(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|一人称|あたし／名前＋さん\nFIELD|二人称|君／苗字＋君／あなた",
            labels={"firstPerson": "一人称", "secondPerson": "二人称"},
            blank_fields={"firstPerson", "secondPerson"},
            allowed_relation_names=set(),
        )

        self.assertEqual(parsed, ({"firstPerson": ["あたし"], "secondPerson": ["君", "あなた"]}, {}))

    def test_profile_suggestion_splits_only_list_fields_on_separator_variants(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|趣味|読書／骨董巡り・散歩,映画鑑賞\nFIELD|二人称|君／あなた・お前",
            labels={"hobbies": "趣味", "secondPerson": "二人称"},
            blank_fields={"hobbies", "secondPerson"},
            allowed_relation_names=set(),
        )

        self.assertEqual(
            parsed, ({"hobbies": "読書／骨董巡り・散歩,映画鑑賞", "secondPerson": ["君", "あなた", "お前"]}, {})
        )

    def test_profile_suggestion_preserves_punctuation_in_free_text_and_relations(self) -> None:
        parsed = parse_profile_suggestion(
            "FIELD|背景・来歴|東京,大阪を転々とし、仕事/私生活を切り替える。\n"
            "RELATION|紗良|関係性|先輩/後輩だが、私生活では友人・相談相手。\n"
            "RELATION|紗良|呼び方|先輩/紗良さん",
            labels={"background": "背景・来歴"},
            blank_fields={"background"},
            allowed_relation_names={"紗良"},
            allowed_relation_fields={"紗良": {"address", "relationship"}},
        )

        self.assertEqual(
            parsed,
            (
                {
                    "background": "東京,大阪を転々とし、仕事/私生活を切り替える。",
                },
                {
                    "紗良": {
                        "address": "先輩/紗良さん",
                        "relationship": "先輩/後輩だが、私生活では友人・相談相手。",
                    }
                },
            ),
        )

    def test_generated_lines_discard_invalid_annotation_items(self) -> None:
        parsed = parse_generated_lines(
            "LINE|カメラが好きです。|楽しそうに|1.2|0.7|📸@before:カメラ;😊@before:存在しない語句;👋@end"
        )

        self.assertEqual(
            parsed,
            [
                {
                    "text": "カメラが好きです。",
                    "stage_direction": "楽しそうに",
                    "speech_rate": 1.2,
                    "gap_seconds": 0.7,
                    "emoji_annotations": [],
                }
            ],
        )

    def test_generated_lines_accept_pipe_separated_annotation_items(self) -> None:
        parsed = parse_generated_lines(
            "LINE|今は、準備を進めているところだよ！|身を乗り出す|1.2|0.8|😊@before:準備を進めている|😆@end"
        )

        self.assertEqual(
            parsed,
            [
                {
                    "text": "今は、準備を進めているところだよ！",
                    "stage_direction": "身を乗り出す",
                    "speech_rate": 1.2,
                    "gap_seconds": 0.8,
                    "emoji_annotations": [{"emoji": "😊", "placement": "before_phrase", "target": "準備を進めている"}],
                }
            ],
        )

    def test_generated_lines_recovers_an_emoji_preview_column(self) -> None:
        parsed = parse_generated_lines("😊あ、そうだ！|あ、そうだ！|明るくハッとした様子で|1.2|0.6|😊@start;😲@end")

        self.assertEqual(
            parsed,
            [
                {
                    "text": "あ、そうだ！",
                    "stage_direction": "明るくハッとした様子で",
                    "speech_rate": 1.2,
                    "gap_seconds": 0.6,
                    "emoji_annotations": [{"emoji": "😊", "placement": "line_start"}],
                }
            ],
        )

    def test_generated_lines_recovers_a_bare_five_column_row(self) -> None:
        parsed = parse_generated_lines("😊あ、そうだ！|思い出したように|1.2|0.6|😊@start;😲@end")

        self.assertEqual(
            parsed,
            [
                {
                    "text": "あ、そうだ！",
                    "stage_direction": "思い出したように",
                    "speech_rate": 1.2,
                    "gap_seconds": 0.6,
                    "emoji_annotations": [{"emoji": "😊", "placement": "line_start"}],
                }
            ],
        )

    def test_profile_suggestion_resolves_relation_by_target_id(self) -> None:
        request = CharacterProfileSuggestionRequest(
            base_url="http://127.0.0.1:11434/v1",
            model="test-model",
            name="新規キャスト",
            profile_details={"age": ""},
            other_casts=[
                {
                    "id": "sara",
                    "name": "紗良",
                    "profile_details": {"familyName": "如月", "givenName": "紗良"},
                }
            ],
        )
        captured: dict[str, object] = {}

        def completion(*_args, **kwargs):
            if "requested_fields" in kwargs["user"]:
                return "FIELD|age|19歳"
            captured.update(kwargs["user"])
            return "RELATION|sara|関係性|知己"

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/profile-suggestion")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request)

        self.assertEqual(result["profileDetails"]["age"], "19歳")
        self.assertEqual(result["profileDetails"]["castRelations"], {"sara": {"relationship": "知己"}})
        other_cast = captured["relation_targets"][0]
        self.assertNotIn("setting_summary", other_cast)
        self.assertEqual(other_cast["relationship_reference"], {"概要": "（設定なし）"})

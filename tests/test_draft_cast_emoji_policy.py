from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import DraftRequest, direct_draft_performance, generate_draft_dialogue


class DraftCastEmojiPolicyTests(unittest.TestCase):
    def test_structured_prompt_shares_rulebook_and_shows_enabled_and_disabled_emoji(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="structured promptのEMOJI契約を確認します。",
            cast_settings={"cast-a": {"emoji_expressions": True}, "cast-b": {"emoji_expressions": False}},
            allowed_emojis=["😊"],
        )
        capabilities = {"structuredOutput": {"streaming": {"state": "schema_validated"}}}
        with (
            patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value=capabilities),
            patch("server.modules.llm_completion_service.complete_records") as completion,
        ):
            completion.return_value.mode = "schema"
            completion.return_value.records = ()
            completion.return_value.manifest = ()
            completion.return_value.transport.partial = False
            completion.return_value.transport.finish_reason = "stop"
            completion.return_value.transport.usage = {}
            generate_draft_dialogue(
                request,
                cast_context=[{"cast": "A", "name": "莉里"}, {"cast": "B", "name": "葵"}],
                plan={"story_bible": "", "chapters": []},
                chapter={"title": "導入", "beats": ["D1.1|挨拶する"]}, chapter_index=0,
                requested_characters=80, remaining_characters=80,
                accepted_dialogue={"lines": []}, continuity_state="", token_budget=2048,
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
            )
        system = completion.call_args.kwargs["system"]
        self.assertIn("【SCENA 表情EMOJI演出ルール】", system)
        self.assertIn("`emoji=😆@楽しい`は正しい", system)
        self.assertIn('"speaker":"A","text":"今日は楽しみだね。","emoji":"😊@楽しみ"', system)
        self.assertIn('"speaker":"B","text":"うん、行こう。","emoji":null', system)
        self.assertIn("falseのspeakerはemojiを必ずnullまたはNONE", system)

    def test_integrated_prompt_uses_cast_level_emoji_permission(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="キャスト別の統合EMOJI設定を確認します。",
            cast_settings={"cast-a": {"emoji_expressions": True}, "cast-b": {"emoji_expressions": False}},
            allowed_emojis=["😊", "😌"], simultaneous_cues=True,
        )
        cast_context = [
            {"cast": "A", "name": "莉里", "preferences": {"emoji": "許可"}},
            {"cast": "B", "name": "葵", "preferences": {"emoji": "禁止"}},
        ]
        with patch(
            "server.modules.llm_client.openai_stream_text_completion",
            return_value="A|おはよう。||emoji=😊@おはよう|rate=1.0",
        ) as completion:
            generate_draft_dialogue(
                request, cast_context=cast_context, plan={"story_bible": "", "chapters": []},
                chapter={"title": "導入"}, chapter_index=0, requested_characters=80,
                remaining_characters=80, accepted_dialogue={"lines": []}, continuity_state="",
                token_budget=2048, cast_alias_by_id={"cast-a": "A", "cast-b": "B"},
            )
        sections = completion.call_args.kwargs["user"]["sections"]
        settings = next(section["request_settings"] for section in sections if "request_settings" in section)
        self.assertNotIn("allowed_emojis", settings)  # listed once, in the system prompt
        self.assertEqual(settings["emoji_enabled_by_cast"], {"A": True, "B": False})
        self.assertEqual(next(section["participating_casts"] for section in sections if "participating_casts" in section), cast_context)
        system = completion.call_args.kwargs["system"]
        self.assertIn("`emoji=😆@楽しい`は正しい", system)
        self.assertIn("`emoji=😆@😆`", system)
        self.assertIn("独立AI演出と同じ基準", system)
        self.assertIn("割り込むB自身へ負値を書くと", system)
        self.assertIn("許可EMOJI: 😊、😌。", system)

    def test_integrated_emoji_is_applied_without_a_second_direction_call(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a"], target_minutes=1, theme="統合EMOJIを最終適用します。",
            cast_settings={"cast-a": {"emoji_expressions": True}}, allowed_emojis=["😊"],
        )
        dialogue = {"lines": [{
            "line_id": "C001L001", "character_id": "cast-a", "text": "おはよう。",
            "integrated_direction_attempted": True,
            "integrated_direction": {"emoji": "😊@おはよう", "rate": "1.05", "direction": "明るく"},
            "integrated_direction_source_text": "おはよう。",
            "integrated_direction_origin": "R1", "integrated_direction_next_origin": "END",
        }]}
        with (
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion") as completion,
        ):
            scenes = direct_draft_performance(
                request, job_id="integrated-emoji", cast_context=[{"cast": "A", "name": "莉里"}],
                chapter={"title": "導入"}, dialogue=dialogue, lookahead_lines=[],
                cast_alias_by_id={"cast-a": "A"}, prior_performance_state="", token_budget=2048,
                debug_directory=Path("/tmp"), chapter_index=0,
            )
        completion.assert_not_called()
        line = scenes[0]["lines"][0]
        self.assertEqual((line["text"], line["speechRate"], line["stageDirection"]), ("😊おはよう。", 1.05, "明るく"))

    def test_discards_emoji_only_for_disabled_cast(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a", "cast-b"], target_minutes=1,
            theme="キャスト別EMOJI設定を確認するテーマです。",
            cast_settings={"cast-a": {"emoji_expressions": True}, "cast-b": {"emoji_expressions": False}},
            allowed_emojis=["😊"],
        )
        dialogue = {"lines": [
            {"line_id": "L1", "character_id": "cast-a", "text": "おはよう。"},
            {"line_id": "L2", "character_id": "cast-b", "text": "待って。"},
        ]}
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.draft_job_state.update_draft_job"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value=(
                "L1|emoji=😊@おはよう|rate=1.0|gap=0.7|direction=明るく\n"
                "L2|emoji=😊@待って|rate=1.2|gap=0.4|direction=焦って"
            )),
        ):
            scenes = direct_draft_performance(
                request, job_id="test-job", cast_context=[{"cast": "A", "name": "莉里"}, {"cast": "B", "name": "葵"}],
                chapter={"title": "導入"}, dialogue=dialogue, lookahead_lines=[],
                cast_alias_by_id={"cast-a": "A", "cast-b": "B"}, prior_performance_state="",
                token_budget=2048, debug_directory=Path("/tmp"), chapter_index=0,
            )
        first, second = scenes[0]["lines"]
        self.assertEqual(first["text"], "😊おはよう。")
        self.assertEqual(second["text"], "待って。")
        self.assertEqual((second["speechRate"], second["gapSeconds"], second["stageDirection"]), (1.2, 0.4, "焦って"))


if __name__ == "__main__":
    unittest.main()

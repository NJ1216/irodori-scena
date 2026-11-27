from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import DraftRequest, create_draft_plan


class DraftOutlinePlanningTests(unittest.TestCase):
    def test_planning_adapts_theme_density_and_uses_duration_led_chapters(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a"], target_minutes=3,
            theme="。".join(f"具体条件{index}" for index in range(120)) + "。",
        )
        captured = {}

        def completion(*_args, **kwargs):
            captured.update(kwargs)
            return "\n".join((
                "TITLE|圧縮する構成",
                "CHAPTER|1|一", "OBJECTIVE|導入", "BEAT|出来事一", "END_CHAPTER",
                "CHAPTER|2|二", "OBJECTIVE|展開", "BEAT|出来事二", "END_CHAPTER",
                "CHAPTER|3|三", "OBJECTIVE|結末", "BEAT|出来事三", "END_CHAPTER",
            ))

        with patch("server.modules.llm_client.openai_text_completion", side_effect=completion):
            plan = create_draft_plan(
                request, cast_context=[{"cast": "A", "name": "彩"}], chunk_count=1,
                target_characters=1_123, token_budget=2_048, debug_directory=Path("/tmp"),
            )
        policy = captured["user"]["theme_adaptation"]
        self.assertEqual((policy["mode"], policy["story_chapters"]), ("compress", 1))
        self.assertEqual(captured["user"]["suggested_story_chapters"], 1)
        self.assertGreater(len(captured["user"]["source_sections"]), 1)
        self.assertEqual(len(plan["chapters"]), 1)
        self.assertEqual(plan["_theme_adaptation"]["mode"], "compress")
        self.assertIn("複数区間を一章へ自然に統合", captured["system"])

    def test_short_theme_fallback_uses_distinct_progression_beats(self) -> None:
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1", model="test-model",
            character_ids=["cast-a"], target_minutes=3, theme="恥ずかしながら自己紹介する。",
        )
        with patch("server.modules.llm_client.openai_text_completion", return_value=""):
            plan = create_draft_plan(
                request, cast_context=[{"cast": "A", "name": "彩"}], chunk_count=1,
                target_characters=1_123, token_budget=2_048, debug_directory=Path("/tmp"),
            )
        beats = plan["chapters"][0]["beats"]
        self.assertGreaterEqual(len(beats), 2)
        self.assertEqual(len(beats), len(set(beats)))
        self.assertNotIn(request.theme, beats)


if __name__ == "__main__":
    unittest.main()

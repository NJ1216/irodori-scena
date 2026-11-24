from __future__ import annotations

import unittest

from server.app import draft_reader_introduction
from server.modules.draft_jobs import _script_cast_contexts
from server.modules.project_repository import repair_draft_cast_context_placeholders


class DraftCastIntroductionTests(unittest.TestCase):
    def test_narrative_plan_description_is_preserved(self) -> None:
        contexts = _script_cast_contexts(
            {"cast_contexts": {"A": {"role": "書店主", "description": "雨の日だけ店を開く、少し皮肉屋の書店主。"}}},
            [{"cast": "A", "reader_facing_introduction_seed": "紗良は書店主として登場する人物。"}],
            {"cast-a": "A"},
        )
        self.assertEqual(contexts["cast-a"]["description"], "雨の日だけ店を開く、少し皮肉屋の書店主。")

    def test_database_style_plan_description_uses_narrative_fallback(self) -> None:
        contexts = _script_cast_contexts(
            {"cast_contexts": {"A": {"role": "書店主", "description": "名前：佐倉 紗良　読み：さくら さら　年齢：24歳"}}},
            [{"cast": "A", "reader_facing_introduction_seed": "紗良は、書店主を務める少し皮肉屋な人物。"}],
            {"cast-a": "A"},
        )
        self.assertEqual(contexts["cast-a"]["description"], "紗良は、書店主を務める少し皮肉屋な人物。")

    def test_fallback_does_not_import_unselected_optional_background(self) -> None:
        introduction = draft_reader_introduction({
            "name": "佐倉 紗良",
            "profileDetails": {"role": "古書店の店主", "personality": "少し皮肉屋", "background": "本好きの客には親切に接する。"},
        })
        self.assertEqual(introduction, "佐倉 紗良は、古書店の店主を務める少し皮肉屋な人物。")
        self.assertNotIn("名前：", introduction)
        self.assertNotIn("読み：", introduction)

    def test_missing_plan_record_keeps_each_cast_role_and_introduction(self) -> None:
        contexts = _script_cast_contexts(
            {"cast_contexts": {}},
            [
                {
                    "cast": "A",
                    "reader_facing_role_seed": "古書店主",
                    "reader_facing_introduction_seed": "紗良は、古書店主を務める少し皮肉屋な人物。",
                },
                {
                    "cast": "B",
                    "reader_facing_role_seed": "常連客",
                    "reader_facing_introduction_seed": "蓮は、店主を気遣う穏やかな常連客。",
                },
            ],
            {"cast-a": "A", "cast-b": "B"},
        )
        self.assertEqual(contexts["cast-a"], {
            "role": "古書店主",
            "description": "紗良は、古書店主を務める少し皮肉屋な人物。",
        })
        self.assertEqual(contexts["cast-b"], {
            "role": "常連客",
            "description": "蓮は、店主を気遣う穏やかな常連客。",
        })

    def test_saved_regression_placeholder_is_repaired_without_touching_user_copy(self) -> None:
        project = {
            "characters": [
                {
                    "id": "cast-a",
                    "name": "紗良",
                    "profileDetails": {"role": "古書店主", "personality": "少し皮肉屋"},
                },
                {"id": "cast-b", "name": "蓮", "profileDetails": {"role": "常連客"}},
            ],
            "scriptCastContexts": {
                "cast-a": {"role": "登場人物", "description": "この台本の登場人物。"},
                "cast-b": {"role": "登場人物", "description": "ユーザーが編集した紹介。"},
            },
        }
        repair_draft_cast_context_placeholders(project)
        self.assertEqual(project["scriptCastContexts"]["cast-a"], {
            "role": "古書店主",
            "description": "紗良は、古書店主を務める少し皮肉屋な人物。",
        })
        self.assertEqual(project["scriptCastContexts"]["cast-b"], {
            "role": "登場人物",
            "description": "ユーザーが編集した紹介。",
        })


if __name__ == "__main__":
    unittest.main()

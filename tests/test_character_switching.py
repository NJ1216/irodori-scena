from __future__ import annotations

import unittest
from types import SimpleNamespace

from server.modules.project_routes import _merge_script_cast_contexts


class CharacterSwitchingTests(unittest.TestCase):
    def test_swap_uses_original_context_snapshot(self) -> None:
        contexts = {
            "a": {"role": "姉", "description": "強気"},
            "b": {"role": "妹", "description": "慎重"},
        }
        mappings = [
            SimpleNamespace(from_character_id="a", to_character_id="b"),
            SimpleNamespace(from_character_id="b", to_character_id="a"),
        ]
        self.assertEqual(_merge_script_cast_contexts(contexts, mappings), {
            "a": {"role": "妹", "description": "慎重"},
            "b": {"role": "姉", "description": "強気"},
        })

    def test_many_to_one_preserves_order_and_removes_duplicates(self) -> None:
        contexts = {
            "a": {"role": "進行", "description": "明るい"},
            "b": {"role": "進行", "description": "慎重"},
        }
        mappings = [
            SimpleNamespace(from_character_id="a", to_character_id="c"),
            SimpleNamespace(from_character_id="b", to_character_id="c"),
        ]
        self.assertEqual(_merge_script_cast_contexts(contexts, mappings)["c"], {
            "role": "進行",
            "description": "明るい\n慎重",
        })

    def test_legacy_setting_moves_into_description(self) -> None:
        result = _merge_script_cast_contexts(
            {"a": {"role": "進行", "setting": "明るい"}},
            [SimpleNamespace(from_character_id="a", to_character_id="c")],
        )
        self.assertEqual(result["c"], {"role": "進行", "description": "明るい"})


if __name__ == "__main__":
    unittest.main()

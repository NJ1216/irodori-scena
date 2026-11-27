from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.app import DraftRequest, compile_cast_context, delete_cast_context


def _character(character_id: str, *, scope: str = "project", profile: str = "快活" * 100) -> dict:
    return {
        "id": character_id, "name": f"人物{character_id}", "scope": scope, "profile": profile,
        "profileDetails": {"role": "書店員", "personality": "慎重", "firstPerson": ["私"], "secondPerson": ["あなた"],
                           "speechStyle": "落ち着いて話す", "castRelations": {}},
    }


class CastContextCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = DraftRequest(base_url="http://127.0.0.1:9999/v1", model="model",
                                    character_ids=["a"], target_minutes=1, theme="テスト用テーマ")

    def test_cache_survives_reload_and_audio_only_changes_do_not_miss(self) -> None:
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
             patch("server.modules.llm_completion_service.complete_records") as completion:
            completion.return_value = SimpleNamespace(records=(
                {"cast": "A", "summary": "明るい人物。", "relation_summaries": []},
            ))
            first, first_audit = compile_cast_context(self.request, [_character("a")], project_id="p1", aliases={"a": "A"})
            changed = {**_character("a"), "audioHash": "new", "referenceFile": "/private/audio.wav"}
            second, second_audit = compile_cast_context(self.request, [changed], project_id="p1", aliases={"a": "A"})
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual((first_audit[0]["cache"], second_audit[0]["cache"]), ("miss", "hit"))

    def test_profile_change_and_corrupt_cache_regenerate(self) -> None:
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
             patch("server.modules.llm_completion_service.complete_records") as completion:
            completion.return_value = SimpleNamespace(records=(
                {"cast": "A", "summary": "概要", "relation_summaries": []},
            ))
            compile_cast_context(self.request, [_character("a")], project_id="p1", aliases={"a": "A"})
            compile_cast_context(self.request, [_character("a", profile="冷静" * 100)], project_id="p1", aliases={"a": "A"})
            cache = Path(directory) / "cache" / "cast-context-summaries.json"
            cache.write_text("broken", encoding="utf-8")
            compile_cast_context(self.request, [_character("a", profile="冷静" * 100)], project_id="p1", aliases={"a": "A"})
        self.assertEqual(completion.call_count, 3)

    def test_global_and_project_scopes_do_not_collide_or_delete_each_other(self) -> None:
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
             patch("server.modules.llm_completion_service.complete_records") as completion:
            completion.return_value = SimpleNamespace(records=(
                {"cast": "A", "summary": "概要", "relation_summaries": []},
            ))
            compile_cast_context(self.request, [_character("a", scope="global")], project_id="p1", aliases={"a": "A"})
            compile_cast_context(self.request, [_character("a")], project_id="p1", aliases={"a": "A"})
            delete_cast_context("project", "a", "p1")
            cache = json.loads((Path(directory) / "cache" / "cast-context-summaries.json").read_text())
        self.assertIn("global:a", cache["entries"])
        self.assertNotIn("project:p1:a", cache["entries"])

    def test_partial_summary_uses_uncached_fallback_and_filters_unselected_relations(self) -> None:
        a, b = _character("a"), _character("b")
        a["profileDetails"]["castRelations"] = {
            "b": {"address": "ビー", "relationship": "幼なじみ"},
            "outside": {"address": "先生", "relationship": "恩師"},
        }
        request = self.request.model_copy(update={"character_ids": ["a", "b"]})
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
             patch("server.modules.llm_completion_service.complete_records") as completion:
            completion.return_value = SimpleNamespace(records=(
                {"cast": "A", "summary": "有効な概要", "relation_summaries": [{"target": "B", "summary": "親しい"}]},
            ))
            context, audit = compile_cast_context(request, [a, b], project_id="p1", aliases={"a": "A", "b": "B"})
            second, second_audit = compile_cast_context(request, [a, b], project_id="p1", aliases={"a": "A", "b": "B"})
        self.assertEqual(context[0]["relations"], [{"target": "B", "name": "人物b", "address": "ビー", "summary": "親しい"}])
        self.assertTrue(audit[1]["fallback"])
        self.assertEqual(second_audit[0]["cache"], "hit")
        self.assertEqual(second_audit[1]["cache"], "miss")
        self.assertTrue(second[1]["summary"])
        self.assertTrue(all(row["promptCharacters"] <= 2000 for row in audit))
        self.assertNotIn("outside", json.dumps(context, ensure_ascii=False))

    def test_context_carries_deterministic_reader_facing_fallbacks(self) -> None:
        character = _character("a", profile="短い設定")
        context, _audit = compile_cast_context(
            self.request, [character], project_id="p1", aliases={"a": "A"}
        )
        self.assertEqual(context[0]["reader_facing_role_seed"], "書店員")
        self.assertEqual(
            context[0]["reader_facing_introduction_seed"],
            "人物aは、書店員を務める慎重な人物。",
        )


if __name__ == "__main__":
    unittest.main()

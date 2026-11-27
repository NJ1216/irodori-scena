import scena_test_isolation  # noqa: F401
import server.app  # noqa: F401  (registers the backend dependencies these modules read)
import unittest

from server.modules.character_profiles import normalized_cast_relations
from server.modules.draft_cast_context import draft_cast_context
from server.modules.draft_cast_phases import draft_chapter_cast_context


class CastRelationsTest(unittest.TestCase):
    def test_chapter_context_keeps_full_profiles_for_speakers_and_references(self) -> None:
        characters = [
            {"id": "a", "name": "A子", "profileDetails": {"personality": "快活", "hobbies": "秘密の趣味"}},
            {"id": "b", "name": "B子", "profileDetails": {"personality": "冷静", "background": "必要な過去"}},
            {"id": "c", "name": "C子", "profile": "送信禁止", "profileDetails": {}},
        ]
        base = draft_cast_context(characters, cast_alias_by_id={"a": "A", "b": "B", "c": "C"})
        selected = draft_chapter_cast_context(base, {
            "speaking_casts": ["A"], "mentioned_casts": ["B"],
            "required_profile_fields": {"B": ["background"]},
        }, characters)
        self.assertEqual([item["cast"] for item in selected], ["A", "B"])
        self.assertIn("秘密の趣味", str(selected))
        self.assertIn("必要な過去", str(selected))
        self.assertNotIn("送信禁止", str(selected))

    def test_normalized_cast_relations_migrates_legacy_values_without_loss(self) -> None:
        legacy = "家がお隣で、昔から互いの秘密を知っている。"
        self.assertEqual(normalized_cast_relations({"a": legacy, "b": {"note": legacy}}), {
            "a": {"relationship": legacy},
            "b": {"relationship": legacy},
        })


    def test_normalized_cast_relations_keeps_subfields_and_limits_them(self) -> None:
        self.assertEqual(normalized_cast_relations({
            " target ": {"address": " あ ", "relationship": " い "},
            "blank": {"address": "  ", "relationship": ""},
            "long": {"address": "呼" * 200, "relationship": "関" * 1300},
        }), {
            "target": {"address": "あ", "relationship": "い"},
            "long": {"address": "呼" * 160, "relationship": "関" * 1200},
        })


    def test_draft_context_separates_address_and_relationship_and_filters_targets(self) -> None:
        characters = [
            {"id": "a", "name": "彩", "profileDetails": {"castRelations": {
                "b": {"address": "リリ", "relationship": "幼なじみで、強がりを見抜く。"},
                "outside": {"address": "先生", "relationship": "恩師"},
            }}},
            {"id": "b", "name": "莉里", "profileDetails": {}},
        ]
        context = draft_cast_context(characters, cast_alias_by_id={"a": "A", "b": "B"})
        self.assertEqual(context[0]["relations"], [{
            "target": "B", "name": "莉里", "address": "リリ",
            "relationship": "幼なじみで、強がりを見抜く。",
        }])
        self.assertEqual(context[1]["relations"], [])

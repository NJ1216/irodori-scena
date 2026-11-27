from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules.pronunciation_dictionary import (
    affected_pronunciation_line_ids, apply_pronunciation_dictionary,
)


class PronunciationDictionaryTests(unittest.TestCase):
    def test_names_resolve_by_speaker_then_active_cast_then_stable_id(self) -> None:
        entries = [
            {"id": "z-inactive", "term": "葵", "reading": "あおい非登場", "source": "cast", "characterId": "inactive", "sourceKeys": ["givenName"]},
            {"id": "z-active", "term": "葵", "reading": "あおい登場Z", "source": "cast", "characterId": "active-z", "sourceKeys": ["displayName"]},
            {"id": "a-active", "term": "葵", "reading": "あおい登場A", "source": "cast", "characterId": "active-a", "sourceKeys": ["familyName"]},
            {"id": "speaker", "term": "葵", "reading": "あおい本人", "source": "cast", "characterId": "self", "sourceKeys": ["givenName"]},
        ]
        active = {"self", "active-z", "active-a", "other"}
        self.assertEqual(apply_pronunciation_dictionary("葵", "self", active, entries), "あおい本人")
        self.assertEqual(apply_pronunciation_dictionary("葵", "other", active, entries), "あおい登場A")
        self.assertEqual(apply_pronunciation_dictionary("葵", "other", active, list(reversed(entries))), "あおい登場A")
        self.assertEqual(apply_pronunciation_dictionary("葵", "other", {"other"}, entries), "あおい登場A")

    def test_mixed_first_person_and_name_entry_is_context_sensitive(self) -> None:
        entries = [{
            "id": "riri", "term": "りり", "reading": "リリ読み", "source": "cast",
            "characterId": "riri", "sourceKeys": ["firstPerson", "givenName"],
        }]
        active = {"riri", "mina"}
        self.assertEqual(apply_pronunciation_dictionary("りり", "riri", active, entries), "リリ読み")
        self.assertEqual(apply_pronunciation_dictionary("りり", "mina", active, entries), "リリ読み")

    def test_manual_and_cast_manual_entries_are_global_and_deterministic(self) -> None:
        cast_manuals = [
            {"id": "z", "term": "SCENA", "reading": "キャストZ", "source": "cast", "characterId": "riri", "sourceKeys": ["manual"]},
            {"id": "a", "term": "SCENA", "reading": "キャストA", "source": "cast", "characterId": "mina", "sourceKeys": ["manual"]},
        ]
        self.assertEqual(apply_pronunciation_dictionary("SCENA", "other", set(), cast_manuals), "キャストA")
        ordinary = {"id": "manual", "term": "SCENA", "reading": "通常", "source": "manual", "sourceKeys": ["manual"]}
        self.assertEqual(apply_pronunciation_dictionary("SCENA", "other", set(), [*cast_manuals, ordinary]), "通常")

    def test_affected_lines_use_speaker_specific_resolution(self) -> None:
        before = [
            {"id": "riri", "term": "私", "reading": "あたし", "source": "cast", "characterId": "riri", "sourceKeys": ["firstPerson"]},
            {"id": "mina", "term": "私", "reading": "わたくし", "source": "cast", "characterId": "mina", "sourceKeys": ["firstPerson"]},
        ]
        after = [{**before[0], "reading": "わたし"}, before[1]]
        def line(line_id: str, character_id: str) -> dict[str, object]:
            return {"id": line_id, "text": "私は", "characterId": character_id,
                    "takes": [{"id": "take"}], "selectedTakeId": "take"}
        project = {"scenes": [{"lines": [line("riri-line", "riri"), line("mina-line", "mina")]}]}
        with patch("server.modules.project_repository.read_project", return_value=project):
            self.assertEqual(affected_pronunciation_line_ids(before, after), ["riri-line"])

    def test_affected_lines_compare_final_rendered_text_and_filter_unusable_lines(self) -> None:
        before = [{"id": "word", "term": "Tokyo", "reading": "とうきょう", "source": "manual"}]
        after = [{"id": "word", "term": "Tokyo", "reading": "とーきょー", "source": "manual"}]
        eligible = {"id": "eligible", "text": "TOKYOへ", "characterId": "cast", "takes": [{"id": "take"}], "selectedTakeId": "take"}
        local = {**eligible, "id": "local", "pronunciations": [{"id": "p", "start": 0, "end": 5, "text": "TOKYO", "reading": "とうきょう"}]}
        disabled = {**eligible, "id": "disabled", "enabled": False}
        ungenerated = {**eligible, "id": "ungenerated", "takes": [], "selectedTakeId": None}
        project = {"scenes": [{"lines": [eligible, local, disabled, ungenerated]}]}
        with patch("server.modules.project_repository.read_project", return_value=project):
            self.assertEqual(affected_pronunciation_line_ids(before, after), ["eligible"])

    def test_affected_lines_ignore_dictionary_changes_with_same_effective_reading(self) -> None:
        before = [{"id": "cast", "term": "Riri", "reading": "りり", "source": "cast", "characterId": "a"}]
        after = [*before, {"id": "manual", "term": "Riri", "reading": "りり", "source": "manual"}]
        line = {"id": "line", "text": "riri", "characterId": "a", "takes": [{"id": "take"}], "selectedTakeId": "take"}
        with patch("server.modules.project_repository.read_project", return_value={"scenes": [{"lines": [line]}]}):
            self.assertEqual(affected_pronunciation_line_ids(before, after), [])




if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException
import server.app  # noqa: F401
from server.modules.line_pronunciations import apply_line_pronunciations, resolve_line_pronunciations
from server.modules.pronunciation_dictionary import (
    _llm_reading_suggestions,
    add_cast_pronunciation_entry, add_manual_pronunciation_entry, apply_pronunciation_dictionary,
    list_pronunciation_dictionary, read_pronunciation_dictionary,
    reconcile_cast_pronunciations, set_pronunciation_lock, sync_character_pronunciations,
    resolve_pronunciation_dictionary, scoped_pronunciation_rows,
    update_cast_pronunciation_reading, write_pronunciation_dictionary,
)
from server.modules.models import PronunciationChangeRequest
from server.modules.pronunciation_routes import _add_manual_to_scopes, _update_project_entry


class PronunciationDictionaryTests(unittest.TestCase):
    def test_add_manual_can_fill_project_when_global_term_is_occupied(self) -> None:
        existing = {"id": "g", "term": "静か", "reading": "しずか", "source": "manual"}
        project = {"pronunciationDictionary": []}
        written: dict[str, object] = {}
        with TemporaryDirectory() as directory, patch("server.modules.constants.PROJECT_FILE", Path(directory) / "project.json"), patch(
            "server.modules.constants.ACTIVE_PROJECT_PATH", None
        ), patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[existing]), patch(
            "server.modules.project_repository.write_project", side_effect=lambda value: written.update(project=value)
        ) as write_project, patch("server.modules.pronunciation_dictionary.write_pronunciation_dictionary") as write_global:
            _add_manual_to_scopes(project, PronunciationChangeRequest(operation="add-manual", term=" 静か ", reading="しーん", scopes=["project"]))
        write_project.assert_called_once()
        write_global.assert_not_called()
        self.assertEqual(written["project"]["pronunciationDictionary"][0]["reading"], "しーん")

    def test_add_manual_restores_project_when_second_destination_fails(self) -> None:
        with TemporaryDirectory() as directory:
            project_file = Path(directory) / "project.json"
            project_file.write_text("before", encoding="utf-8")
            def write_project(_value: object) -> None:
                project_file.write_text("partial", encoding="utf-8")
            with patch("server.modules.constants.PROJECT_FILE", project_file), patch(
                "server.modules.constants.ACTIVE_PROJECT_PATH", None
            ), patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]), patch(
                "server.modules.project_repository.write_project", side_effect=write_project
            ), patch("server.modules.pronunciation_dictionary.write_pronunciation_dictionary", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    _add_manual_to_scopes({"pronunciationDictionary": []}, PronunciationChangeRequest(operation="add-manual", term="Tokyo", reading="とうきょう", scopes=["global", "project"]))
            self.assertEqual(project_file.read_text(encoding="utf-8"), "before")

    def test_project_entry_precedes_global_and_nonconflicting_global_falls_back(self) -> None:
        entries = [
            {"id": "project", "term": "東京", "reading": "とうけい", "source": "manual", "scope": "project"},
            {"id": "global-tokyo", "term": "東京", "reading": "とうきょう", "source": "manual", "scope": "global"},
            {"id": "global-osaka", "term": "大阪", "reading": "おおさか", "source": "manual", "scope": "global"},
        ]
        rendered, used = resolve_pronunciation_dictionary("東京と大阪", "cast", {"cast"}, entries)
        self.assertEqual(rendered, "とうけいとおおさか")
        self.assertEqual(used, {"global-osaka"})

    def test_line_local_reading_prevents_global_entry_from_being_reported_used(self) -> None:
        rendered, used = resolve_line_pronunciations(
            "東京と大阪", [{"start": 0, "end": 2, "text": "東京", "reading": "ひがしきょう"}], "cast", {"cast"},
            [{"id": "tokyo", "term": "東京", "reading": "とうきょう", "source": "manual", "scope": "global"}],
        )
        self.assertEqual(rendered, "ひがしきょうと大阪")
        self.assertEqual(used, set())

    def test_equal_scoped_entries_merge_but_different_versions_remain_rows(self) -> None:
        global_entries = [{"id": "g", "term": "API", "reading": "えーぴーあい", "source": "manual", "sourceKeys": ["manual"], "userEdited": True}]
        project = {"pronunciationDictionary": [
            {**global_entries[0], "id": "p"},
            {"id": "other", "term": "東京", "reading": "とうけい", "source": "manual"},
        ]}
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=global_entries):
            rows = scoped_pronunciation_rows(project)
        api = next(row for row in rows if row["term"] == "API")
        self.assertEqual(api["scopes"], ["global", "project"])
        self.assertTrue(api["merged"])

    def test_project_edit_rejects_a_duplicate_term_within_project(self) -> None:
        project = {"pronunciationDictionary": [
            {"id": "one", "term": "東京", "reading": "とうきょう", "source": "manual"},
            {"id": "two", "term": "大阪", "reading": "おおさか", "source": "manual"},
        ]}
        with self.assertRaisesRegex(HTTPException, "同じ語句はPROJECT"):
            _update_project_entry(project, "two", "東京", "とうけい", False)
        self.assertEqual(project["pronunciationDictionary"][1]["term"], "大阪")

    def test_reading_suggestion_prepares_the_built_in_llm_runtime(self) -> None:
        selected = {"provider": "scena-local", "baseUrl": "http://scena.local/v1", "model": "local-model", "apiKey": "", "settings": {"temperature": 0}}
        with patch("server.modules.llm_registry.resolve_default_llm", return_value=selected), patch(
            "server.modules.local_llm_runtime.load_local_llm"
        ) as load, patch(
            "server.modules.local_llm_runtime.local_llm_runtime_endpoint", return_value="http://127.0.0.1:54321/v1"
        ), patch(
            "server.modules.local_llm_runtime.local_llm_runtime_api_key", return_value="runtime-key"
        ), patch(
            "server.modules.pronunciation_dictionary._request_llm_reading_suggestions", return_value={"Riri": "りり"}
        ) as request:
            result = _llm_reading_suggestions({"name": "Riri"}, ["Riri"], [], [])
        self.assertEqual(result, {"Riri": "りり"})
        load.assert_called_once_with("local-model", settings={"temperature": 0})
        self.assertEqual(request.call_args.args[0]["baseUrl"], "http://127.0.0.1:54321/v1")
        self.assertEqual(request.call_args.args[0]["apiKey"], "runtime-key")

    def test_reading_suggestion_does_not_prepare_an_external_runtime(self) -> None:
        selected = {"provider": "ollama", "baseUrl": "http://127.0.0.1:11434/v1", "model": "model", "apiKey": ""}
        with patch("server.modules.llm_registry.resolve_default_llm", return_value=selected), patch(
            "server.modules.local_llm_runtime.load_local_llm"
        ) as load, patch(
            "server.modules.pronunciation_dictionary._request_llm_reading_suggestions", return_value={}
        ) as request:
            _llm_reading_suggestions({"name": "Riri"}, ["Riri"], [], [])
        load.assert_not_called()
        self.assertEqual(request.call_args.args[0]["baseUrl"], "http://127.0.0.1:11434/v1")

    def test_line_readings_override_dictionary_and_invalid_siblings_are_ignored(self) -> None:
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)):
            write_pronunciation_dictionary([
                {"id": "tokyo", "term": "東京", "reading": "とうきょう", "source": "manual"},
                {"id": "osaka", "term": "大阪", "reading": "おおさか", "source": "manual"},
            ])
            result = apply_line_pronunciations("😀東京と大阪", [
                {"id": "local", "start": 1, "end": 3, "text": "東京", "reading": "ひがしきょう"},
                {"id": "broken", "start": 4, "end": 6, "text": "不一致", "reading": "ignored"},
            ], "cast-any")
        self.assertEqual(result, "😀ひがしきょうとおおさか")

    def test_read_is_side_effect_free(self) -> None:
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), patch("server.modules.workspace.ensure_data_root") as ensure:
            self.assertEqual(list_pronunciation_dictionary(), [])
        ensure.assert_not_called()

    def test_reconcile_uses_only_supported_fields_without_llm(self) -> None:
        character = {"id": "mina", "name": "朝霧 碧", "profile": "漆黒の魔導書", "profileDetails": {
            "familyName": "朝霧", "familyNameKana": "あさぎり", "givenName": "碧", "givenNameKana": "あおい",
            "firstPerson": ["私", "わたし"], "secondPerson": ["あなた"], "aliases": ["ミナ先輩"],
        }}
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), patch("server.modules.pronunciation_dictionary._llm_reading_suggestions") as llm:
            reconcile_cast_pronunciations([character])
            entries = read_pronunciation_dictionary()
        self.assertEqual({(e["term"], e["reading"]) for e in entries}, {
            ("朝霧", "あさぎり"), ("碧", "あおい"), ("私", ""), ("わたし", "わたし"),
        })
        self.assertFalse({"あなた", "ミナ先輩", "漆黒"} & {e["term"] for e in entries})
        llm.assert_not_called()

    def test_duplicate_terms_merge_source_keys(self) -> None:
        character = {"id": "riri", "name": "りり", "profileDetails": {"givenName": "りり", "firstPerson": ["りり"]}}
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)):
            reconcile_cast_pronunciations([character])
            entries = read_pronunciation_dictionary()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["reading"], "りり")
        self.assertEqual(entries[0]["sourceKeys"], ["firstPerson", "givenName"])

    def test_display_name_matching_full_name_is_omitted_with_or_without_spaces(self) -> None:
        characters = [
            {"id": "spaced", "name": "朝霧 碧", "profileDetails": {"familyName": "朝霧", "givenName": "碧"}},
            {"id": "compact", "name": "如月紗良", "profileDetails": {"familyName": "如月", "givenName": "紗良"}},
        ]
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)):
            reconcile_cast_pronunciations(characters)
            entries = read_pronunciation_dictionary()
        self.assertNotIn("朝霧 碧", {entry["term"] for entry in entries})
        self.assertNotIn("如月紗良", {entry["term"] for entry in entries})
        self.assertEqual({entry["term"] for entry in entries}, {"朝霧", "碧", "如月", "紗良"})

    def test_edited_and_locked_readings_survive(self) -> None:
        character = {"id": "riri", "name": "Riri", "profileDetails": {"firstPerson": ["吾輩"]}}
        existing = [
            {"id": "name", "term": "Riri", "reading": "りり", "source": "cast", "characterId": "riri", "sourceKeys": ["displayName"], "userEdited": True},
            {"id": "first", "term": "吾輩", "reading": "わがはい", "source": "cast", "characterId": "riri", "sourceKeys": ["firstPerson"], "locked": True},
        ]
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)):
            write_pronunciation_dictionary(existing)
            reconcile_cast_pronunciations([character])
            readings = {e["term"]: e["reading"] for e in read_pronunciation_dictionary()}
        self.assertEqual(readings, {"Riri": "りり", "吾輩": "わがはい"})

    def test_stale_cast_and_legacy_script_entries_are_removed(self) -> None:
        existing = [
            {"id": "alias", "term": "旧愛称", "reading": "きゅう", "source": "cast", "characterId": "riri", "sourceKeys": ["profile"]},
            {"id": "manual", "term": "専用語", "reading": "せんようご", "source": "cast", "characterId": "riri", "sourceKeys": ["manual"]},
            {"id": "gone", "term": "Gone", "reading": "ごーん", "source": "cast", "characterId": "gone", "sourceKeys": ["manual"]},
            {"id": "script", "term": "VST3", "reading": "ぶいえすてぃー", "source": "manual", "sourceKeys": ["script"], "userEdited": True, "locked": True},
            {"id": "ordinary", "term": "東京", "reading": "とうきょう", "source": "manual", "sourceKeys": ["manual"]},
        ]
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)):
            write_pronunciation_dictionary(existing)
            reconcile_cast_pronunciations([{"id": "riri", "name": "Riri", "profileDetails": {}}])
            ids = {e["id"] for e in read_pronunciation_dictionary()}
        self.assertTrue({"manual", "ordinary"} <= ids)
        self.assertFalse({"alias", "gone", "script"} & ids)

    def test_sync_keeps_global_casts_outside_the_current_project(self) -> None:
        library_cast = {
            "id": "library-cast",
            "name": "図書",
            "profileDetails": {"familyName": "図書", "familyNameKana": "としょ"},
        }
        project_cast = {"id": "project-cast", "name": "旧名", "profileDetails": {}}
        renamed_cast = {**project_cast, "name": "白凪 芳祈"}
        with (
            TemporaryDirectory() as directory,
            patch("server.modules.constants.DATA_ROOT", Path(directory)),
            patch("server.modules.project_repository.read_global_characters", return_value=[library_cast]),
            patch("server.modules.project_repository.read_project", return_value={"characters": [project_cast]}),
        ):
            reconcile_cast_pronunciations([library_cast, project_cast])
            sync_character_pronunciations(renamed_cast)
            entries = read_pronunciation_dictionary()

        by_cast = {entry["characterId"]: entry["term"] for entry in entries}
        self.assertEqual(by_cast, {"library-cast": "図書", "project-cast": "白凪 芳祈"})

    def test_manual_cast_entry_and_reading_controls_remain_supported(self) -> None:
        character = {"id": "riri", "name": "Riri", "profileDetails": {}}
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), patch("server.modules.project_repository.read_project", return_value={"characters": [character]}):
            reconcile_cast_pronunciations([character])
            manual = add_cast_pronunciation_entry("riri", "専用語", "せんようご")
            automatic = next(e for e in read_pronunciation_dictionary() if e["term"] == "Riri")
            update_cast_pronunciation_reading(automatic["id"], "りり")
            set_pronunciation_lock(automatic["id"], True)
            reconcile_cast_pronunciations([character])
            entries = read_pronunciation_dictionary()
        self.assertIn(manual["id"], {e["id"] for e in entries})
        self.assertTrue(next(e for e in entries if e["id"] == automatic["id"])["locked"])

    def test_reading_accepts_kanji_latin_and_mixed_text(self) -> None:
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)):
            first = add_manual_pronunciation_entry("API", "英単語の読み")
            second = add_manual_pronunciation_entry("SCENA", "Scene風")
            third = add_manual_pronunciation_entry("再生成", "さい・せいせい")
        self.assertEqual(first["reading"], "英単語の読み")
        self.assertEqual(second["reading"], "Scene風")
        self.assertEqual(third["reading"], "さい・せいせい")

    def test_manual_dictionary_keeps_tts_precedence(self) -> None:
        with TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)):
            write_pronunciation_dictionary([
                {"id": "cast", "term": "Riri", "reading": "りり", "source": "cast", "characterId": "riri"},
                {"id": "manual", "term": "Riri", "reading": "りりさん", "source": "manual"},
            ])
            self.assertEqual(apply_pronunciation_dictionary("Riri", "riri"), "りりさん")

    def test_first_person_readings_apply_only_to_the_owning_speaker(self) -> None:
        entries = [
            {"id": "riri-first", "term": "私", "reading": "あたし", "source": "cast", "characterId": "riri", "sourceKeys": ["firstPerson"]},
            {"id": "mina-first", "term": "私", "reading": "わたくし", "source": "cast", "characterId": "mina", "sourceKeys": ["firstPerson"]},
        ]
        active = {"riri", "mina", "narrator"}
        self.assertEqual(apply_pronunciation_dictionary("私は", "riri", active, entries), "あたしは")
        self.assertEqual(apply_pronunciation_dictionary("私は", "mina", active, entries), "わたくしは")
        self.assertEqual(apply_pronunciation_dictionary("私は", "narrator", active, entries), "私は")




if __name__ == "__main__":
    unittest.main()

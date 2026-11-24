from __future__ import annotations

import unittest
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException
import server.app  # noqa: F401
from server.modules.models import PronunciationChangeRequest
from server.modules.pronunciation_routes import _add_manual_to_scopes, _update_project_entry, change_pronunciation_dictionary
from server.modules.project_pronunciation_snapshot import (
    change_project_pronunciation,
    reconcile_script_pronunciations,
    script_pronunciation_signature,
)
from server.modules.project_repository import _reconcile_script_dictionary_after_change


class PronunciationDictionaryTests(unittest.TestCase):
    def test_concurrent_updates_keep_both_words(self) -> None:
        from server.modules import pronunciation_dictionary as dictionary
        directory = Path.cwd() / f".dictionary-test-{uuid4().hex}"
        directory.mkdir()
        try:
            with patch.object(dictionary, "dictionary_file", return_value=directory / "words.json"):
                start = Event()
                project = {"scenes": [], "pronunciationDictionary": [
                    {"id": "project-tokyo", "term": "Tokyo", "reading": "とうきょう", "source": "manual"},
                    {"id": "project-osaka", "term": "Osaka", "reading": "おおさか", "source": "manual"},
                ]}
                def enable(entry_id: str) -> None:
                    self.assertTrue(start.wait(5))
                    change_pronunciation_dictionary(PronunciationChangeRequest(
                        operation="toggle-scope", scope="global", enabled=True, project_id=entry_id,
                    ))
                with patch("server.modules.project_repository.read_project", return_value=project):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        first = pool.submit(enable, "project-tokyo")
                        second = pool.submit(enable, "project-osaka")
                        start.set()
                        first.result(timeout=5)
                        second.result(timeout=5)
                saved = json.loads((directory / "words.json").read_text(encoding="utf-8"))
                self.assertEqual({entry["term"] for entry in saved}, {"Tokyo", "Osaka"})
        finally:
            (directory / "words.json").unlink(missing_ok=True)
            directory.rmdir()

    def test_failed_replace_preserves_file_and_cleans_temporary(self) -> None:
        from server.modules import pronunciation_dictionary as dictionary
        directory = Path.cwd() / f".dictionary-test-{uuid4().hex}"
        directory.mkdir()
        try:
            with patch.object(dictionary, "dictionary_file", return_value=directory / "words.json"):
                path = directory / "words.json"
                path.write_text('[]\n', encoding="utf-8")
                with patch.object(Path, "replace", side_effect=OSError("replace failed")):
                    with self.assertRaisesRegex(OSError, "replace failed"):
                        dictionary.write_pronunciation_dictionary([{"term": "Tokyo"}])
                self.assertEqual(path.read_text(encoding="utf-8"), '[]\n')
                self.assertEqual(list(directory.iterdir()), [path])
        finally:
            (directory / "words.json").unlink(missing_ok=True)
            directory.rmdir()

    def test_script_reconciliation_adds_used_global_manual_entry(self) -> None:
        global_entry = {"id": "global-api", "term": "API", "reading": "えーぴーあい", "source": "manual"}
        project = {"scenes": [{"lines": [{"id": "line", "characterId": "cast", "text": "APIを使う"}]}], "pronunciationDictionary": []}
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[global_entry]), patch(
            "server.modules.common.new_id", return_value="project-api"
        ):
            self.assertTrue(reconcile_script_pronunciations(project))
        self.assertEqual(project["pronunciationDictionary"], [{
            **global_entry, "id": "project-api", "projectScopeOrigin": "script-auto",
        }])

    def test_script_reconciliation_removes_only_unused_auto_entries(self) -> None:
        global_entries = [
            {"id": "g-api", "term": "API", "reading": "えーぴーあい", "source": "manual"},
            {"id": "g-ui", "term": "UI", "reading": "ゆーあい", "source": "manual"},
        ]
        project = {
            "scenes": [{"lines": [{"id": "disabled", "characterId": "cast", "text": "API", "enabled": False}]}],
            "pronunciationDictionary": [
                {**global_entries[0], "id": "p-api", "projectScopeOrigin": "script-auto"},
                {**global_entries[1], "id": "p-ui", "projectScopeOrigin": "script-auto"},
                {"id": "manual", "term": "保存", "reading": "ほぞん", "source": "manual", "projectScopeOrigin": "manual"},
                {"id": "legacy", "term": "外部", "reading": "がいぶ", "source": "manual"},
            ],
        }
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=global_entries):
            self.assertTrue(reconcile_script_pronunciations(project))
        self.assertEqual({entry["id"] for entry in project["pronunciationDictionary"]}, {"p-api", "manual", "legacy"})

    def test_script_reconciliation_keeps_auto_entry_when_scena_source_changed(self) -> None:
        project_entry = {
            "id": "project", "term": "API", "reading": "えーぴーあい", "source": "manual",
            "projectScopeOrigin": "script-auto",
        }
        project = {"scenes": [{"lines": []}], "pronunciationDictionary": [project_entry]}
        changed_global = {"id": "global", "term": "API", "reading": "あぴ", "source": "manual"}
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[changed_global]):
            self.assertFalse(reconcile_script_pronunciations(project))
        self.assertEqual(project["pronunciationDictionary"], [project_entry])

    def test_script_reconciliation_respects_line_local_reading_and_project_priority(self) -> None:
        global_entries = [
            {"id": "g-tokyo", "term": "東京", "reading": "とうきょう", "source": "manual"},
            {"id": "g-osaka", "term": "大阪", "reading": "おおさか", "source": "manual"},
        ]
        project = {
            "scenes": [{"lines": [{
                "id": "line", "characterId": "cast", "text": "東京と大阪",
                "pronunciations": [{"start": 0, "end": 2, "text": "東京", "reading": "ひがしきょう"}],
            }]}],
            "pronunciationDictionary": [
                {"id": "project-osaka", "term": "大阪", "reading": "おおざか", "source": "manual"},
            ],
        }
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=global_entries):
            self.assertFalse(reconcile_script_pronunciations(project))
        self.assertEqual([entry["id"] for entry in project["pronunciationDictionary"]], ["project-osaka"])

    def test_load_reconciliation_adds_without_removing_unused_auto_entry(self) -> None:
        used = {"id": "g-used", "term": "API", "reading": "えーぴーあい", "source": "manual"}
        unused = {"id": "p-unused", "term": "UI", "reading": "ゆーあい", "source": "manual", "projectScopeOrigin": "script-auto"}
        project = {
            "scenes": [{"lines": [{"id": "line", "characterId": "cast", "text": "API"}]}],
            "pronunciationDictionary": [unused],
        }
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[used]), patch(
            "server.modules.common.new_id", return_value="p-used"
        ):
            self.assertTrue(reconcile_script_pronunciations(project, add_only=True))
        self.assertEqual({entry["id"] for entry in project["pronunciationDictionary"]}, {"p-unused", "p-used"})

    def test_script_signature_ignores_settings_dictionary_and_enabled_state(self) -> None:
        project = {
            "settings": {"speechRate": 1.2},
            "pronunciationDictionary": [],
            "scenes": [{"lines": [{"id": "line", "characterId": "cast", "text": "API", "enabled": True}]}],
        }
        changed = {**project, "settings": {"speechRate": 0.8}, "pronunciationDictionary": [{"id": "entry"}]}
        changed["scenes"] = [{"lines": [{**project["scenes"][0]["lines"][0], "enabled": False}]}]
        self.assertEqual(script_pronunciation_signature(project), script_pronunciation_signature(changed))

    def test_explicit_project_enable_promotes_existing_auto_entry_to_manual(self) -> None:
        source = {"id": "global", "term": "API", "reading": "えーぴーあい", "source": "manual"}
        project = {"pronunciationDictionary": [{
            **source, "id": "project", "projectScopeOrigin": "script-auto",
        }]}
        change_project_pronunciation(project, entry_id="project", source_entry=source)
        self.assertEqual(project["pronunciationDictionary"][0]["projectScopeOrigin"], "manual")

    def test_editing_project_entry_marks_it_manual(self) -> None:
        project = {"pronunciationDictionary": [{
            "id": "project", "term": "API", "reading": "えーぴーあい", "source": "manual",
            "projectScopeOrigin": "script-auto",
        }]}
        _update_project_entry(project, "project", "API", "エーピーアイ", None)
        self.assertEqual(project["pronunciationDictionary"][0]["projectScopeOrigin"], "manual")

    def test_multiple_lines_keep_auto_entry_until_last_use_is_removed(self) -> None:
        global_entry = {"id": "global", "term": "SCENA", "reading": "しーな", "source": "manual"}
        auto_entry = {**global_entry, "id": "project", "projectScopeOrigin": "script-auto"}
        project = {
            "scenes": [{"lines": [
                {"id": "one", "characterId": "cast", "text": "SCENA"},
                {"id": "two", "characterId": "cast", "text": "SCENA"},
            ]}],
            "pronunciationDictionary": [auto_entry],
        }
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[global_entry]):
            project["scenes"][0]["lines"].pop()
            self.assertFalse(reconcile_script_pronunciations(project))
            project["scenes"][0]["lines"].clear()
            self.assertTrue(reconcile_script_pronunciations(project))
        self.assertEqual(project["pronunciationDictionary"], [])

    def test_reconciliation_uses_case_insensitive_longest_term_resolution(self) -> None:
        global_entries = [
            {"id": "short", "term": "API", "reading": "えーぴーあい", "source": "manual"},
            {"id": "long", "term": "API Server", "reading": "えーぴーあいさーばー", "source": "manual"},
        ]
        project = {
            "scenes": [{"lines": [{"id": "line", "characterId": "cast", "text": "api server"}]}],
            "pronunciationDictionary": [],
        }
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=global_entries):
            self.assertTrue(reconcile_script_pronunciations(project))
        self.assertEqual([entry["term"] for entry in project["pronunciationDictionary"]], ["API Server"])

    def test_reconciliation_runs_only_when_saved_script_signature_changes(self) -> None:
        persisted = {"settings": {"speechRate": 1.2}, "scenes": [{"lines": [{"id": "line", "text": "before"}]}]}
        settings_change = {"settings": {"speechRate": 0.8}, "scenes": persisted["scenes"]}
        text_change = {"settings": persisted["settings"], "scenes": [{"lines": [{"id": "line", "text": "after"}]}]}
        with patch("server.modules.project_pronunciation_snapshot.reconcile_script_pronunciations") as reconcile:
            _reconcile_script_dictionary_after_change(settings_change, persisted)
            reconcile.assert_not_called()
            _reconcile_script_dictionary_after_change(text_change, persisted)
            reconcile.assert_called_once_with(text_change)

    def test_large_script_reconciliation_visits_each_line_once_at_save_boundary(self) -> None:
        entries = [
            {"id": f"global-{index}", "term": f"TERM{index}", "reading": f"よみ{index}", "source": "manual"}
            for index in range(100)
        ]
        project = {
            "scenes": [{"lines": [
                {"id": f"line-{index}", "characterId": "cast", "text": f"TERM{index % 100}"}
                for index in range(1_000)
            ]}],
            "pronunciationDictionary": [],
        }
        from server.modules.line_pronunciations import resolve_line_pronunciations as resolve
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=entries), patch(
            "server.modules.line_pronunciations.resolve_line_pronunciations", wraps=resolve
        ) as resolve_each_line:
            self.assertTrue(reconcile_script_pronunciations(project))
        self.assertEqual(resolve_each_line.call_count, 1_000)
        self.assertEqual(len(project["pronunciationDictionary"]), 100)

    def test_add_manual_to_both_scopes_is_one_validated_operation(self) -> None:
        project = {"pronunciationDictionary": []}
        written: dict[str, object] = {}
        with TemporaryDirectory() as directory, patch("server.modules.constants.PROJECT_FILE", Path(directory) / "project.json"), patch(
            "server.modules.constants.ACTIVE_PROJECT_PATH", None
        ), patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]), patch(
            "server.modules.project_repository.write_project", side_effect=lambda value: written.update(project=value)
        ) as write_project, patch(
            "server.modules.pronunciation_dictionary.write_pronunciation_dictionary", side_effect=lambda value: written.update(global_entries=value)
        ) as write_global:
            _add_manual_to_scopes(project, PronunciationChangeRequest(operation="add-manual", term=" Tokyo ", reading="とうきょう", scopes=["global", "project"]))
        write_project.assert_called_once()
        write_global.assert_called_once()
        self.assertEqual(written["project"]["pronunciationDictionary"][0]["term"], "Tokyo")
        self.assertEqual(written["global_entries"][0]["reading"], "とうきょう")

    def test_add_manual_rejects_occupied_scope_before_either_write(self) -> None:
        existing = {"id": "g", "term": "TOKYO", "reading": "old", "source": "manual"}
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[existing]), patch(
            "server.modules.project_repository.write_project"
        ) as write_project, patch("server.modules.pronunciation_dictionary.write_pronunciation_dictionary") as write_global:
            with self.assertRaisesRegex(HTTPException, "一件だけ"):
                _add_manual_to_scopes({"pronunciationDictionary": []}, PronunciationChangeRequest(operation="add-manual", term="tokyo", reading="new", scopes=["global", "project"]))
        write_project.assert_not_called()
        write_global.assert_not_called()




if __name__ == "__main__":
    unittest.main()

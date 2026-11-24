from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app as _app  # noqa: F401
from server.modules import constants
from server.modules import history


class LinePronunciationHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        # Scratch fixtures must never inherit the user's saved container.
        self.enterContext(patch.object(constants, "ACTIVE_PROJECT_PATH", None))
        sync = self.enterContext(patch("server.modules.project_container.sync_project_entry"))
        self.addCleanup(sync.assert_not_called)

    def _change(self, project_file: Path, pronunciations: list[dict[str, str]]) -> None:
        before = history.capture_history_before("script")
        self._write(project_file, pronunciations)
        history.commit_history("script", before)

    @staticmethod
    def _write(project_file: Path, pronunciations: list[dict[str, str]]) -> None:
        project_file.write_text(
            json.dumps({"scenes": [{"lines": [{"pronunciations": pronunciations}]}]}), encoding="utf-8"
        )

    @staticmethod
    def _read(project_file: Path) -> list[dict[str, str]]:
        return json.loads(project_file.read_text(encoding="utf-8"))["scenes"][0]["lines"][0]["pronunciations"]

    def test_character_history_restores_its_pronunciation_entries(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            global_file = root / "global-characters.json"
            dictionary_file = root / "pronunciation-dictionary.json"
            media_root, global_media_root = root / "media", root / "global-media"
            media_root.mkdir()
            global_media_root.mkdir()
            project_file.write_text('{"characters":[],"scenes":[]}', encoding="utf-8")
            global_file.write_text('[{"id":"cast-1"}]', encoding="utf-8")
            dictionary_file.write_text('[{"id":"word-1","characterId":"cast-1"}]', encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", global_file),
            ):
                history.begin_history_session()
                before = history.capture_history_before("characters")
                global_file.write_text("[]", encoding="utf-8")
                dictionary_file.write_text("[]", encoding="utf-8")
                history.commit_history("characters", before)
                history.apply_history("characters", "undo")

            self.assertIn("cast-1", global_file.read_text(encoding="utf-8"))
            self.assertIn("word-1", dictionary_file.read_text(encoding="utf-8"))

    def test_add_edit_and_delete_are_independent_undo_entries(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            media_root = root / "media"
            global_media_root = root / "global-media"
            media_root.mkdir()
            global_media_root.mkdir()
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", root / "global-characters.json"),
            ):
                history.begin_history_session()
                self._write(project_file, [])
                self._change(project_file, [{"id": "ruby", "reading": "よみ"}])
                self._change(project_file, [{"id": "ruby", "reading": "へんこう"}])
                self._change(project_file, [])

                self.assertEqual(self._read(project_file), [])
                history.apply_history("script", "undo")
                self.assertEqual(self._read(project_file)[0]["reading"], "へんこう")
                history.apply_history("script", "undo")
                self.assertEqual(self._read(project_file)[0]["reading"], "よみ")
                history.apply_history("script", "undo")
                self.assertEqual(self._read(project_file), [])

                history.apply_history("script", "redo")
                self.assertEqual(self._read(project_file)[0]["reading"], "よみ")
                history.apply_history("script", "redo")
                self.assertEqual(self._read(project_file)[0]["reading"], "へんこう")
                history.apply_history("script", "redo")
                self.assertEqual(self._read(project_file), [])

    def test_script_history_restores_text_and_auto_project_dictionary_together(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            (root / "media").mkdir()
            (root / "global-media").mkdir()
            before_project = {
                "scenes": [{"lines": [{"id": "line", "text": "API"}]}],
                "pronunciationDictionary": [{
                    "id": "auto", "term": "API", "reading": "えーぴーあい",
                    "source": "manual", "projectScopeOrigin": "script-auto",
                }],
            }
            after_project = {"scenes": [{"lines": [{"id": "line", "text": "変更後"}]}], "pronunciationDictionary": []}
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", root / "global-media"),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", root / "global.json"),
            ):
                history.begin_history_session()
                project_file.write_text(json.dumps(before_project), encoding="utf-8")
                snapshot = history.capture_history_before("script")
                project_file.write_text(json.dumps(after_project), encoding="utf-8")
                history.commit_history("script", snapshot)
                history.apply_history("script", "undo")
                self.assertEqual(json.loads(project_file.read_text(encoding="utf-8")), before_project)
                history.apply_history("script", "redo")
                self.assertEqual(json.loads(project_file.read_text(encoding="utf-8")), after_project)

    def test_non_script_history_preserves_files_owned_by_other_scopes(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            global_characters_file = root / "global-characters.json"
            dictionary_file = root / "pronunciation-dictionary.json"
            media_root = root / "media"
            global_media_root = root / "global-media"
            media_root.mkdir()
            global_media_root.mkdir()
            project_file.write_text('{"title":"project"}', encoding="utf-8")
            global_characters_file.write_text('[{"id":"global-cast"}]', encoding="utf-8")
            dictionary_file.write_text('{"entries":[{"term":"色彩"}]}', encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", global_characters_file),
            ):
                history.begin_history_session()
                before = history.capture_history_before("pronunciation")
                dictionary_file.write_text('{"entries":[]}', encoding="utf-8")
                history.commit_history("pronunciation", before)
                history.apply_history("pronunciation", "undo")
                self.assertTrue(global_characters_file.is_file())

                before = history.capture_history_before("characters")
                global_characters_file.write_text("[]", encoding="utf-8")
                history.commit_history("characters", before)
                history.apply_history("characters", "undo")
                self.assertTrue(dictionary_file.is_file())

    def test_character_history_never_deletes_media_absent_from_snapshot(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            global_file = root / "global-characters.json"
            dictionary_file = root / "pronunciation-dictionary.json"
            media_root, global_media_root = root / "media", root / "global-media"
            media_root.mkdir()
            global_media_root.mkdir()
            project_file.write_text('{"characters":[],"scenes":[]}', encoding="utf-8")
            global_file.write_text("[]", encoding="utf-8")
            dictionary_file.write_text("[]", encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", global_file),
            ):
                history.begin_history_session()
                before = history.capture_history_before("characters")
                global_file.write_text('[{"id":"cast-1"}]', encoding="utf-8")
                avatar = global_media_root / "characters" / "cast-1" / "avatar-original.png"
                avatar.parent.mkdir(parents=True)
                avatar.write_bytes(b"avatar")
                history.commit_history("characters", before)
                history.apply_history("characters", "undo")

            self.assertEqual(avatar.read_bytes(), b"avatar")
            self.assertEqual(global_file.read_text(encoding="utf-8"), "[]")

    def test_character_history_rejects_snapshot_with_missing_referenced_media(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            global_file = root / "global-characters.json"
            dictionary_file = root / "pronunciation-dictionary.json"
            media_root, global_media_root = root / "media", root / "global-media"
            media_root.mkdir()
            global_media_root.mkdir()
            project_file.write_text('{"characters":[],"scenes":[]}', encoding="utf-8")
            global_file.write_text(
                '[{"id":"cast-1","avatarUrl":"/global-media/characters/cast-1/avatar.png"}]',
                encoding="utf-8",
            )
            dictionary_file.write_text("[]", encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", global_file),
            ):
                history.begin_history_session()
                snapshot = history.capture_history_before("characters")
                sentinel = global_media_root / "do-not-delete.bin"
                sentinel.write_bytes(b"safe")
                with self.assertRaisesRegex(HTTPException, "画像または音声を欠いた履歴"):
                    history._restore(snapshot)

            self.assertEqual(sentinel.read_bytes(), b"safe")
            self.assertIn("cast-1", global_file.read_text(encoding="utf-8"))




if __name__ == "__main__":
    unittest.main()

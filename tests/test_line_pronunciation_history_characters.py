from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app as _app  # noqa: F401
from server.modules import constants
from server.modules import history


class LinePronunciationHistoryTests(unittest.TestCase):
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

    def test_character_history_checks_only_character_media_boundary(self) -> None:
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
                unrelated = global_media_root / "unrelated.bin"
                unrelated.write_bytes(b"before")
                before = history.capture_history_before("characters")
                global_file.write_text('[{"id":"cast-1"}]', encoding="utf-8")
                history.commit_history("characters", before)
                unrelated.write_bytes(b"newer")
                avatar = global_media_root / "characters" / "cast-1" / "avatar.png"
                avatar.parent.mkdir(parents=True)
                avatar.write_bytes(b"newer")
                with self.assertRaisesRegex(HTTPException, "安全に適用できません"):
                    history.apply_history("characters", "undo")

            self.assertEqual(unrelated.read_bytes(), b"newer")
            self.assertEqual(avatar.read_bytes(), b"newer")
            self.assertIn("cast-1", global_file.read_text(encoding="utf-8"))

    def test_character_history_does_not_scan_unrelated_project_media(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            global_file = root / "global-characters.json"
            dictionary_file = root / "pronunciation-dictionary.json"
            media_root, global_media_root = root / "media", root / "global-media"
            take = media_root / "takes" / "line-1" / "take.wav"
            avatar = global_media_root / "characters" / "cast-1" / "avatar.png"
            take.parent.mkdir(parents=True)
            avatar.parent.mkdir(parents=True)
            take.write_bytes(b"large take")
            avatar.write_bytes(b"avatar")
            project_file.write_text(
                '{"characters":[],"scenes":[{"lines":[{"takes":[{"audioUrl":"/media/takes/line-1/take.wav"}]}]}]}',
                encoding="utf-8",
            )
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
                snapshot = history.capture_history_before("characters")
                history._restore(snapshot)

            self.assertNotIn("media/takes/line-1/take.wav", snapshot["files"])
            self.assertIn("global-media/characters/cast-1/avatar.png", snapshot["files"])

    def test_two_character_deletions_can_be_undone_and_redone_in_sequence(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            global_file = root / "global-characters.json"
            dictionary_file = root / "pronunciation-dictionary.json"
            media_root, global_media_root = root / "media", root / "global-media"
            media_root.mkdir()
            for character_id in ("cast-1", "cast-2"):
                avatar = global_media_root / "characters" / character_id / "avatar.png"
                avatar.parent.mkdir(parents=True, exist_ok=True)
                avatar.write_bytes(character_id.encode())
            project_file.write_text('{"characters":[],"scenes":[]}', encoding="utf-8")
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
                global_file.write_text('[{"id":"cast-1"},{"id":"cast-2"}]', encoding="utf-8")
                first = history.capture_history_before("characters")
                global_file.write_text('[{"id":"cast-2"}]', encoding="utf-8")
                shutil.rmtree(global_media_root / "characters" / "cast-1")
                history.commit_history("characters", first)
                second = history.capture_history_before("characters")
                global_file.write_text("[]", encoding="utf-8")
                shutil.rmtree(global_media_root / "characters" / "cast-2")
                history.commit_history("characters", second)

                history.apply_history("characters", "undo")
                history.apply_history("characters", "undo")
                history.apply_history("characters", "redo")
                history.apply_history("characters", "redo")

            self.assertEqual(global_file.read_text(encoding="utf-8"), "[]")
            self.assertFalse((global_media_root / "characters" / "cast-1" / "avatar.png").exists())
            self.assertFalse((global_media_root / "characters" / "cast-2" / "avatar.png").exists())




if __name__ == "__main__":
    unittest.main()

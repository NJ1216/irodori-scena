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

    def test_cast_undo_preserves_audio_generated_after_cast_deletion(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            media_root = root / "media"
            global_media_root = root / "global-media"
            media_root.mkdir()
            global_media_root.mkdir()
            global_file = root / "global-characters.json"
            global_file.write_text("[]", encoding="utf-8")
            project_file.write_text(json.dumps({"revision": 1, "characters": [{"id": "cast"}], "scenes": []}), encoding="utf-8")
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
                project_file.write_text(json.dumps({"revision": 2, "characters": [], "scenes": []}), encoding="utf-8")
                history.commit_history("characters", before)
                project_file.write_text(json.dumps({"revision": 3, "characters": [], "scenes": [{"lines": [{"id": "line", "takes": [{"audioUrl": "/media/takes/new.wav"}]}]}]}), encoding="utf-8")
                take = media_root / "takes" / "new.wav"
                take.parent.mkdir()
                take.write_bytes(b"generated")

                history.apply_history("characters", "undo")
                restored = json.loads(project_file.read_text(encoding="utf-8"))
                self.assertEqual(restored["characters"], [{"id": "cast"}])
                self.assertEqual(restored["scenes"][0]["lines"][0]["takes"][0]["audioUrl"], "/media/takes/new.wav")
                self.assertEqual(take.read_bytes(), b"generated")
                history.apply_history("characters", "redo")
                self.assertEqual(json.loads(project_file.read_text(encoding="utf-8"))["characters"], [])

    def test_batch_edit_and_auto_renders_restore_as_one_history_entry(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            media_root = root / "media"
            media_root.mkdir()
            takes = [media_root / f"take-{index}.wav" for index in range(3)]
            for take in takes:
                take.write_bytes(b"old")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
            ):
                history.begin_history_session()
                project_file.write_text(json.dumps({"revision": 1, "rates": [1, 1, 1]}), encoding="utf-8")
                before = history.capture_history_before("script")
                project_file.write_text(json.dumps({"revision": 2, "rates": [1.1, 1.1, 1.1]}), encoding="utf-8")
                history.commit_history("script", before)
                for index, take in enumerate(takes):
                    render_before = history.capture_history_before("script", include_media=True)
                    take.write_bytes(f"new-{index}".encode())
                    project_file.write_text(json.dumps({"revision": index + 3, "rates": [1.1, 1.1, 1.1]}), encoding="utf-8")
                    history.commit_history("script", render_before, auto_render_base_revision=2)
                self.assertEqual(history.history_status("script")["canUndo"], True)
                self.assertEqual(len(history._HISTORY["script"]), 1)
                history.apply_history("script", "undo")
                self.assertEqual(json.loads(project_file.read_text())["rates"], [1, 1, 1])
                self.assertEqual([take.read_bytes() for take in takes], [b"old"] * 3)
                history.apply_history("script", "redo")
                self.assertEqual(json.loads(project_file.read_text())["rates"], [1.1] * 3)
                self.assertEqual([take.read_bytes() for take in takes], [b"new-0", b"new-1", b"new-2"])

    def test_auto_render_does_not_merge_across_an_intervening_edit(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            media_root = root / "media"
            media_root.mkdir()
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
            ):
                history.begin_history_session()
                project_file.write_text('{"revision":1}', encoding="utf-8")
                before = history.capture_history_before("script")
                project_file.write_text('{"revision":2}', encoding="utf-8")
                history.commit_history("script", before)
                intervening = history.capture_history_before("script")
                project_file.write_text('{"revision":3}', encoding="utf-8")
                history.commit_history("script", intervening)
                render_before = history.capture_history_before("script", include_media=True)
                project_file.write_text('{"revision":4}', encoding="utf-8")
                history.commit_history("script", render_before, auto_render_base_revision=2)
                self.assertEqual(len(history._HISTORY["script"]), 3)

    def test_new_session_preserves_another_recent_process_session(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory, patch.object(constants, "DATA_ROOT", Path(directory)):
            other = Path(directory) / "undo-sessions" / "another-process" / "blobs"
            other.mkdir(parents=True)
            marker = other / "active"
            marker.write_bytes(b"active")

            history.begin_history_session()

            self.assertEqual(marker.read_bytes(), b"active")

    def test_snapshot_recovers_when_its_session_directory_was_removed(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            project_file.write_text('{"title":"recover"}', encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
            ):
                history.begin_history_session()
                for session in (root / "undo-sessions").iterdir():
                    if session.is_dir():
                        session.rename(root / "removed-session")

                snapshot = history.capture_history_before("pronunciation")

                self.assertEqual(
                    snapshot["files"]["project.json"], history.hashlib.sha256(project_file.read_bytes()).hexdigest()
                )

    def test_script_history_preserves_global_casts_dictionary_and_media(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            media_root = root / "media"
            global_media_root = root / "global-media"
            global_characters_file = root / "global-characters.json"
            dictionary_file = root / "pronunciation-dictionary.json"
            media_root.mkdir()
            global_media_root.mkdir()
            audio = media_root / "large.wav"
            audio.write_bytes(b"audio")
            global_characters_file.write_text('[{"id":"global-cast","name":"保存済み"}]', encoding="utf-8")
            dictionary_file.write_text('{"entries":[{"term":"色彩","reading":"しきさい"}]}', encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", global_characters_file),
            ):
                history.begin_history_session()
                project_file.write_text('{"title":"before"}', encoding="utf-8")
                before = history.capture_history_before("script")
                project_file.write_text('{"title":"after"}', encoding="utf-8")
                history.commit_history("script", before)
                history.apply_history("script", "undo")
                self.assertEqual(audio.read_bytes(), b"audio")
                self.assertEqual(json.loads(global_characters_file.read_text(encoding="utf-8"))[0]["id"], "global-cast")
                self.assertEqual(json.loads(dictionary_file.read_text(encoding="utf-8"))["entries"][0]["term"], "色彩")

    def test_destructive_script_routes_capture_media(self) -> None:
        routes = (
            ("/api/scenes/scene-1/lines/line-1", "DELETE"),
            ("/api/lines/batch-delete", "POST"),
            ("/api/scenes/scene-1", "DELETE"),
            ("/api/project/clear-takes", "POST"),
            ("/api/lines/line-1/takes/take-1", "DELETE"),
        )
        for path, method in routes:
            with self.subTest(path=path):
                self.assertTrue(history._mutates_media(path, method))

    def test_media_snapshot_restores_deleted_take(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file, media_root = root / "project.json", root / "media"
            global_media_root = root / "global-media"
            take = media_root / "takes" / "line-1" / "take.wav"
            take.parent.mkdir(parents=True)
            global_media_root.mkdir()
            take.write_bytes(b"take")
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", root / "global.json"),
            ):
                history.begin_history_session()
                project_file.write_text('{"scenes":[{"lines":[{"id":"line-1"}]}]}', encoding="utf-8")
                before = history.capture_history_before("script", include_media=True)
                take.unlink()
                project_file.write_text('{"scenes":[{"lines":[]}]}', encoding="utf-8")
                history.commit_history("script", before)
                history.apply_history("script", "undo")

            self.assertEqual(take.read_bytes(), b"take")

    def test_stale_history_cannot_overwrite_a_newer_project(self) -> None:
        self.addCleanup(history.begin_history_session)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            media_root, global_media_root = root / "media", root / "global-media"
            media_root.mkdir()
            global_media_root.mkdir()
            with (
                patch.object(constants, "DATA_ROOT", root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media_root),
                patch.object(constants, "GLOBAL_MEDIA_ROOT", global_media_root),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", root / "global.json"),
            ):
                history.begin_history_session()
                project_file.write_text('{"title":"before"}', encoding="utf-8")
                before = history.capture_history_before("script")
                project_file.write_text('{"title":"after"}', encoding="utf-8")
                history.commit_history("script", before)
                project_file.write_text('{"title":"newer background save"}', encoding="utf-8")
                with self.assertRaises(HTTPException) as error:
                    history.apply_history("script", "undo")

            self.assertEqual(error.exception.status_code, 409)
            self.assertIn("newer background save", project_file.read_text(encoding="utf-8"))




if __name__ == "__main__":
    unittest.main()

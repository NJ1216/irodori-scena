from __future__ import annotations

import scena_test_isolation  # noqa: F401
import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from fastapi.testclient import TestClient
from server.app import app
from server.modules import constants, history


class HistoryMediaTargetTests(unittest.TestCase):
    def test_generated_takes_undo_and_redo_without_derived_cache_conflicts(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            old_take = media / "takes/line-1/old.wav"
            new_take = media / "takes/line-1/new.wav"
            cache = media / "cache/derived.wav"
            old_take.parent.mkdir(parents=True)
            old_take.write_bytes(b"old audio")
            old = {"audioUrl": "/media/takes/line-1/old.wav", "seed": 11}
            new = {"audioUrl": "/media/takes/line-1/new.wav", "seed": 22}
            before_project = {"revision": 1, "scenes": [{"lines": [{"takes": [old]}]}]}
            after_project = {"revision": 2, "scenes": [{"lines": [{"takes": [old, new]}]}]}
            project_file.write_text(json.dumps(before_project), encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
            ):
                history.begin_history_session()
                before = history.capture_history_before("script", True, ["takes/line-1"])
                new_take.write_bytes(b"new audio")
                project_file.write_text(json.dumps(after_project), encoding="utf-8")
                history.commit_history("script", before)
                cache.parent.mkdir(parents=True)
                cache.write_bytes(b"playback cache")
                history.apply_history("script", "undo")
                self.assertEqual(json.loads(project_file.read_text()), {**before_project, "revision": 3})
                self.assertFalse(new_take.exists())
                history.apply_history("script", "redo")
                self.assertEqual(json.loads(project_file.read_text()), {**after_project, "revision": 4})
                self.assertEqual(new_take.read_bytes(), b"new audio")
                self.assertEqual(cache.read_bytes(), b"playback cache")
                history.end_history_session()

    def test_overwritten_take_undo_restores_original_audio_after_cache_creation(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            take = media / "takes/line-1/take.wav"
            take.parent.mkdir(parents=True)
            take.write_bytes(b"original")
            project_file.write_text('{"revision":1,"takes":[{"seed":11}]}', encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
            ):
                history.begin_history_session()
                before = history.capture_history_before("script", True, ["takes"])
                take.write_bytes(b"replacement")
                project_file.write_text('{"revision":2,"takes":[{"seed":22}]}', encoding="utf-8")
                history.commit_history("script", before)
                cache = media / "cache/derived.wav"
                cache.parent.mkdir(parents=True)
                cache.write_bytes(b"playback cache")
                history.apply_history("script", "undo")
                self.assertEqual(take.read_bytes(), b"original")
                self.assertEqual(json.loads(project_file.read_text())["takes"][0]["seed"], 11)
                history.apply_history("script", "redo")
                self.assertEqual(take.read_bytes(), b"replacement")
                self.assertEqual(json.loads(project_file.read_text())["takes"][0]["seed"], 22)
                history.end_history_session()

    def test_line_deletion_snapshots_only_the_target_lines_take_tree(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            project_file.write_text('{"id":"project"}', encoding="utf-8")
            first = media / "takes/line-1/take.wav"
            second = media / "takes/line-2/take.wav"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
            ):
                history.begin_history_session()
                snapshot = history.capture_history_before("script", True, ["takes/line-1"])
                second.write_bytes(b"changed outside target")
                matches = history._live_metadata_matches(snapshot)
                history.end_history_session()

            self.assertIn("media/takes/line-1/take.wav", snapshot["files"])
            self.assertNotIn("media/takes/line-2/take.wav", snapshot["files"])
            self.assertTrue(matches)

    def test_line_delete_undo_restores_target_without_requiring_unrelated_media_in_snapshot(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            first = media / "takes/line-1/take.wav"
            second = media / "takes/line-2/take.wav"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            before_project = {
                "scenes": [
                    {
                        "lines": [
                            {"id": "line-1", "takes": [{"audioUrl": "/media/takes/line-1/take.wav"}]},
                            {"id": "line-2", "takes": [{"audioUrl": "/media/takes/line-2/take.wav"}]},
                        ]
                    }
                ]
            }
            after_project = {"scenes": [{"lines": [before_project["scenes"][0]["lines"][1]]}]}
            project_file.write_text(json.dumps(before_project), encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
            ):
                history.begin_history_session()
                before = history.capture_history_before("script", True, ["takes/line-1"])
                project_file.write_text(json.dumps(after_project), encoding="utf-8")
                first.unlink()
                history.commit_history("script", before)

                with patch("server.modules.derived_audio_preparation.reset_overlap_preparation") as reset_plan:
                    undo_response = TestClient(app).post("/api/history/script/undo")
                reset_plan.assert_called_once_with()
                status = undo_response.json()
                restored = json.loads(project_file.read_text(encoding="utf-8"))
                restored_first = first.read_bytes()
                redo_response = TestClient(app).post("/api/history/script/redo")
                redo_status = redo_response.json()
                redone = json.loads(project_file.read_text(encoding="utf-8"))
                history.end_history_session()

            self.assertEqual(undo_response.status_code, 200)
            self.assertFalse(status["canUndo"])
            self.assertTrue(status["canRedo"])
            self.assertEqual(restored, before_project)
            self.assertEqual(restored_first, b"first")
            self.assertEqual(redo_response.status_code, 200)
            self.assertTrue(redo_status["canUndo"])
            self.assertEqual(redone, after_project)
            self.assertFalse(first.exists())
            self.assertEqual(second.read_bytes(), b"second")

    def test_scene_delete_undo_ignores_new_derived_cache_and_restores_its_takes(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            take = media / "takes/scene-line/take.wav"
            take.parent.mkdir(parents=True)
            take.write_bytes(b"scene audio")
            before_project = {"scenes": [{"id": "scene-one", "lines": [{"id": "scene-line", "takes": [{"audioUrl": "/media/takes/scene-line/take.wav"}]}]}]}
            project_file.write_text(json.dumps(before_project), encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
            ):
                history.begin_history_session()
                with patch("server.modules.project_repository.read_project", return_value=before_project):
                    targets = history._scene_delete_media_targets("/api/scenes/scene-one", "DELETE")
                self.assertEqual(targets, ["takes/scene-line"])
                before = history.capture_history_before("script", True, targets)
                project_file.write_text('{"scenes":[]}', encoding="utf-8")
                take.unlink()
                history.commit_history("script", before)
                cache = media / "cache/derived.wav"
                cache.parent.mkdir(parents=True)
                cache.write_bytes(b"new cache")
                history.apply_history("script", "undo")
                self.assertEqual(json.loads(project_file.read_text()), before_project)
                self.assertEqual(take.read_bytes(), b"scene audio")
                self.assertEqual(cache.read_bytes(), b"new cache")
                history.end_history_session()

    def test_empty_scene_delete_does_not_scan_unrelated_media(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            unrelated = media / "cache/derived.wav"
            unrelated.parent.mkdir(parents=True)
            unrelated.write_bytes(b"before")
            project_file.write_text('{"scenes":[]}', encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
            ):
                history.begin_history_session()
                snapshot = history.capture_history_before("script", True, [])
                unrelated.write_bytes(b"after")
                self.assertTrue(history._live_metadata_matches(snapshot))
                history.end_history_session()

    def test_batch_delete_request_resolves_safe_target_directories(self) -> None:
        request = SimpleNamespace(
            method="POST",
            url=SimpleNamespace(path="/api/lines/batch-delete"),
            json=lambda: _async_value({"line_ids": ["line-2", "line-1"]}),
        )

        targets = asyncio.run(history._batch_delete_media_targets(request))

        self.assertEqual(targets, ["takes/line-2", "takes/line-1"])



async def _async_value(value):
    return value



if __name__ == "__main__":
    unittest.main()

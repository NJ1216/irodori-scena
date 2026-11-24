from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import server.app  # noqa: F401
from fastapi import HTTPException
from server.modules import constants, history


class HistoryBoundedIoTests(unittest.TestCase):
    def test_generation_group_repeated_line_keeps_initial_before_and_final_after(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file, media = root / "project.json", root / "media"
            take = media / "takes/line-1/take.wav"
            take.parent.mkdir(parents=True)
            take.write_bytes(b"initial")
            project_file.write_text('{"revision":1,"take":"initial"}', encoding="utf-8")
            group_id = str(uuid4())
            with self._project_paths(root, project_file, media):
                history.begin_history_session()
                for revision, value in ((2, b"middle"), (3, b"final")):
                    before = history.capture_history_before("script", True, ["takes/line-1"])
                    take.write_bytes(value)
                    project_file.write_text(json.dumps({"revision": revision, "take": value.decode()}), encoding="utf-8")
                    history.commit_history("script", before, generation_group_id=group_id)
                self.assertEqual(len(history._HISTORY["script"]), 1)
                history.apply_history("script", "undo")
                self.assertEqual((take.read_bytes(), json.loads(project_file.read_text())["take"]), (b"initial", "initial"))
                history.apply_history("script", "redo")
                self.assertEqual((take.read_bytes(), json.loads(project_file.read_text())["take"]), (b"final", "final"))
                history.end_history_session()

    def test_target_history_never_opens_hundreds_of_unrelated_takes(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file, media = root / "project.json", root / "media"
            target = media / "takes/target/take.wav"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"target")
            for index in range(300):
                unrelated = media / f"takes/unrelated-{index}/take.wav"
                unrelated.parent.mkdir(parents=True)
                unrelated.write_bytes(b"unrelated")
            project_file.write_text('{"revision":1}', encoding="utf-8")
            with self._project_paths(root, project_file, media):
                history.begin_history_session()
                with patch.object(history, "_copy_blob", wraps=history._copy_blob) as copy_blob:
                    snapshot = history.capture_history_before("script", True, ["takes/target"])
                    self.assertTrue(history._live_metadata_matches(snapshot))
                history.end_history_session()
            opened = {call.args[0].resolve() for call in copy_blob.call_args_list}
            self.assertEqual(opened, {project_file.resolve(), target.resolve()})

    def test_missing_required_wav_rejects_undo_before_mutating_live_state(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file, media = root / "project.json", root / "media"
            take = media / "takes/line-1/take.wav"
            take.parent.mkdir(parents=True)
            take.write_bytes(b"before")
            before_project = {"revision": 1, "audioUrl": "/media/takes/line-1/take.wav"}
            after_project = {"revision": 2, "audioUrl": "/media/takes/line-1/take.wav"}
            project_file.write_text(json.dumps(before_project), encoding="utf-8")
            with self._project_paths(root, project_file, media):
                history.begin_history_session()
                before = history.capture_history_before("script", True, ["takes/line-1"])
                take.write_bytes(b"after")
                project_file.write_text(json.dumps(after_project), encoding="utf-8")
                history.commit_history("script", before)
                del history._HISTORY["script"][0]["before"]["files"]["media/takes/line-1/take.wav"]
                with self.assertRaises(HTTPException):
                    history.apply_history("script", "undo")
                self.assertEqual(json.loads(project_file.read_text()), after_project)
                self.assertEqual(take.read_bytes(), b"after")
                history.end_history_session()

    @staticmethod
    def _project_paths(root: Path, project_file: Path, media: Path):
        return _PatchGroup(
            patch.object(constants, "DATA_ROOT", root / "data"),
            patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
            patch.object(constants, "PROJECT_FILE", project_file),
            patch.object(constants, "MEDIA_ROOT", media),
            patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
        )


class _PatchGroup:
    def __init__(self, *patchers):
        self.patchers = patchers

    def __enter__(self):
        for patcher in self.patchers:
            patcher.start()
        return self

    def __exit__(self, *args):
        for patcher in reversed(self.patchers):
            patcher.stop()

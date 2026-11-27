from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.app import app as _app  # noqa: F401
from server.modules import constants, project_container, workspace, workspace_restore


class WorkspaceRestoreTests(unittest.TestCase):
    def test_restore_validates_before_switching_and_preserves_rejected_data(self) -> None:
        for content in ("{}", "{", "[]"):
            with self.subTest(content=content), TemporaryDirectory() as directory:
                base = Path(directory)
                source = base / "source"
                source.mkdir()
                (source / "project.json").write_text(content, encoding="utf-8")
                saved = base / "saved.scena"
                project_container.sync_container(saved, source)
                original = saved.read_bytes()
                data = base / "scena-data"
                data.mkdir()
                state = data / "app-state.json"
                state.write_text(json.dumps({"activeProjectPath": str(saved)}), encoding="utf-8")
                state_bytes = state.read_bytes()
                scratch = data / "project.json"
                scratch.write_text(json.dumps(workspace.default_project()), encoding="utf-8")
                scratch_bytes = scratch.read_bytes()
                with (
                    patch.object(constants, "DATA_ROOT", data),
                    patch.object(constants, "APP_STATE_FILE", state),
                    patch.object(constants, "ACTIVE_PROJECT_ROOT", data),
                    patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                    patch.object(constants, "PROJECT_FILE", scratch),
                    patch.object(constants, "MEDIA_ROOT", data / "media"),
                ):
                    cache = project_container.working_root(saved)
                    cache.mkdir(parents=True)
                    (cache / "sentinel").write_bytes(b"existing cache")
                    with self.assertLogs(workspace_restore.logger, level="WARNING"):
                        workspace.restore_active_workspace()
                    self.assertIsNone(constants.ACTIVE_PROJECT_PATH)
                    self.assertEqual(constants.PROJECT_FILE, scratch.resolve())
                    self.assertEqual((cache / "sentinel").read_bytes(), b"existing cache")
                    self.assertFalse(cache.with_name(f"{cache.name}-restore-preflight").exists())
                self.assertEqual(saved.read_bytes(), original)
                self.assertEqual(state.read_bytes(), state_bytes)
                self.assertEqual(scratch.read_bytes(), scratch_bytes)

    def test_valid_saved_project_is_restored(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "source"
            source.mkdir()
            project = workspace.default_project()
            project["title"] = "復元する作品"
            (source / "project.json").write_text(json.dumps(project), encoding="utf-8")
            saved = base / "saved.scena"
            project_container.sync_container(saved, source)
            data = base / "scena-data"
            data.mkdir()
            state = data / "app-state.json"
            state.write_text(json.dumps({"activeProjectPath": str(saved)}), encoding="utf-8")
            original = saved.read_bytes()
            with (
                patch.object(constants, "DATA_ROOT", data),
                patch.object(constants, "APP_STATE_FILE", state),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", data),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(constants, "PROJECT_FILE", data / "project.json"),
                patch.object(constants, "MEDIA_ROOT", data / "media"),
            ):
                try:
                    workspace.restore_active_workspace()
                    self.assertEqual(constants.ACTIVE_PROJECT_PATH, saved.resolve())
                    self.assertEqual(json.loads(constants.PROJECT_FILE.read_text()), project)
                    self.assertEqual(saved.read_bytes(), original)
                finally:
                    project_container.release_container_lock()

    def test_invalid_app_state_falls_back_to_scratch(self) -> None:
        for state_value in ([], {"activeProjectPath": None}):
            with self.subTest(state_value=state_value), TemporaryDirectory() as directory:
                state = Path(directory) / "app-state.json"
                state.write_text(json.dumps(state_value), encoding="utf-8")
                with (
                    patch.object(constants, "APP_STATE_FILE", state),
                    patch.object(constants, "DATA_ROOT", Path(directory)),
                    patch.object(workspace, "activate_project_root") as activate,
                    self.assertLogs(workspace_restore.logger, level="WARNING"),
                ):
                    workspace.restore_active_workspace()
                activate.assert_called_once_with(Path(directory).resolve(), persist=False)

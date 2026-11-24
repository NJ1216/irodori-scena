from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.app import app
from server.modules import constants, project_backup_service, project_container, workspace


class ProjectBackupTests(unittest.TestCase):
    def _saved_project(self, root: Path) -> tuple[Path, Path, dict]:
        working = root / "working"
        working.mkdir()
        project = workspace.default_project()
        (working / "project.json").write_text(json.dumps(project), encoding="utf-8")
        (working / "media/takes").mkdir(parents=True)
        (working / "media/takes/take.wav").write_bytes(b"audio")
        (working / "unknown.bin").write_bytes(b"unknown")
        (working / "empty").mkdir()
        source = root / "active.scena"
        project_container.sync_container(source, working)
        return source, working, project

    def _backup(self, root: Path, destination: Path) -> dict:
        source, working, project = self._saved_project(root)
        with (
            patch.object(constants, "ACTIVE_PROJECT_PATH", source),
            patch.object(constants, "ACTIVE_PROJECT_ROOT", working),
            patch.object(constants, "DATA_ROOT", root / "scena-data"),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.media_integrity.reconcile_project_media", return_value=0),
        ):
            return project_backup_service.backup_project(str(destination))

    def test_creates_valid_snapshot_without_switching_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "copy.scena"
            result = self._backup(root, destination)
            extracted = root / "extracted"
            project_container.extract_container(destination, extracted)
            self.assertEqual((extracted / "media/takes/take.wav").read_bytes(), b"audio")
            self.assertEqual((extracted / "unknown.bin").read_bytes(), b"unknown")
            self.assertTrue((extracted / "empty").is_dir())
            self.assertEqual(result["backup"]["path"], str(destination.resolve()))

    def test_failed_validation_preserves_existing_backup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            destination = root / "copy.scena"
            destination.write_bytes(b"old")
            source, working, project = self._saved_project(root)
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", source),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", working),
                patch.object(constants, "DATA_ROOT", root / "scena-data"),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.media_integrity.reconcile_project_media", return_value=0),
                patch.object(project_container, "validate_container", side_effect=OSError("invalid snapshot")),
                self.assertRaisesRegex(OSError, "invalid snapshot"),
            ):
                project_backup_service.backup_project(str(destination))
            self.assertEqual(destination.read_bytes(), b"old")
            self.assertEqual(list(root.glob(".copy.*.scena")), [])

    def test_rejects_invalid_internal_self_and_directory_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "active.scena"
            source.write_bytes(b"source")
            data_root = root / "scena-data"
            data_root.mkdir()
            directory = root / "directory.scena"
            directory.mkdir()
            with patch.object(constants, "ACTIVE_PROJECT_PATH", source), patch.object(constants, "DATA_ROOT", data_root):
                for destination in (root / "copy.zip", source, data_root / "copy.scena", directory):
                    with self.subTest(destination=destination), self.assertRaises(HTTPException):
                        project_backup_service._validate_destination(destination)

    def test_rejects_unsaved_project_and_running_jobs(self) -> None:
        with patch.object(constants, "ACTIVE_PROJECT_PATH", None), self.assertRaisesRegex(HTTPException, "先に"):
            project_backup_service.backup_project("/tmp/copy.scena")
        with patch("server.modules.export_service.active_draft_job", return_value=True), patch("server.modules.export_service.active_export_job", return_value=False):
            response = TestClient(app).post("/api/project/backup", json={"path": "/tmp/copy.scena"})
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()

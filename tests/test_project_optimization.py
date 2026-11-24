from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import create_app
from server.modules import constants, project_container, project_routes


class ProjectOptimizationTests(unittest.TestCase):
    def setUp(self) -> None:
        create_app()

    def test_saved_project_runs_cleanup_without_switching_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            saved = Path(directory) / "project.scena"
            saved.write_bytes(b"saved project")
            project = {"scenes": [], "characters": []}
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(project_routes, "_require_workspace_switch_available"),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.media_integrity.reconcile_project_media", return_value=0),
                patch("server.modules.project_cache_cleanup.cleanup_loaded_project") as cleanup,
            ):
                result = project_routes.optimize_project()
            cleanup.assert_called_once_with(project)
            self.assertEqual(result["beforeBytes"], saved.stat().st_size)
            self.assertEqual(result["afterBytes"], saved.stat().st_size)
            self.assertEqual(result["project"], project)

    def test_scratch_project_must_be_saved_first(self) -> None:
        with (
            patch.object(constants, "ACTIVE_PROJECT_PATH", None),
            patch.object(project_routes, "_require_workspace_switch_available"),
        ):
            with self.assertRaises(HTTPException) as raised:
                project_routes.optimize_project()
        self.assertEqual(raised.exception.status_code, 409)
        with patch.object(constants, "ACTIVE_PROJECT_PATH", None):
            self.assertEqual(project_routes.project_optimization_status(), {"available": False})

    def test_manual_optimization_reduces_the_open_project_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, saved = base / "work", base / "project.scena"
            root.mkdir()
            project = {"scenes": [{"lines": []}], "characters": []}
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            stale = root / "media/cache/overlap-mixes/old.wav"
            stale.parent.mkdir(parents=True)
            stale.write_bytes(os.urandom(1024 * 1024))
            project_container.sync_container(saved, root)
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(project_routes, "_require_workspace_switch_available"),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.media_integrity.reconcile_project_media", return_value=0),
            ):
                self.assertEqual(project_routes.project_optimization_status(), {"available": True})
                result = project_routes.optimize_project()
                self.assertEqual(project_routes.project_optimization_status(), {"available": False})
            self.assertLess(result["afterBytes"], result["beforeBytes"] // 2)
            self.assertFalse(stale.exists())

    def test_free_sqlite_pages_enable_optimization_without_orphan_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, saved = base / "work", base / "project.scena"
            root.mkdir()
            project = {"scenes": [{"lines": []}], "characters": []}
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            project_container.sync_container(saved, root)
            with closing(sqlite3.connect(saved)) as connection:
                with connection:
                    connection.execute(
                        "INSERT INTO entries VALUES ('unused.bin','file','none',?, ?, zeroblob(?))",
                        (1024 * 1024, "0" * 64, 1024 * 1024),
                    )
                with connection:
                    connection.execute("DELETE FROM entries WHERE path='unused.bin'")
                self.assertGreater(connection.execute("PRAGMA freelist_count").fetchone()[0], 0)
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(project_routes, "_require_workspace_switch_available"),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.media_integrity.reconcile_project_media", return_value=0),
            ):
                self.assertEqual(project_routes.project_optimization_status(), {"available": True})
                result = project_routes.optimize_project()
                self.assertEqual(project_routes.project_optimization_status(), {"available": False})
            self.assertLess(result["afterBytes"], result["beforeBytes"] // 2)


if __name__ == "__main__":
    unittest.main()

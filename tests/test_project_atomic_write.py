from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

import server.app  # noqa: F401
from server.modules import constants, project_repository, workspace


class ProjectAtomicWriteTests(unittest.TestCase):
    def test_ordinary_write_excludes_derived_audio_and_refreshes_active_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            container = root / "saved.scena"
            with (
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(constants, "ACTIVE_PROJECT_PATH", container),
                patch("server.modules.project_pronunciation_snapshot.project_pronunciation_snapshot", return_value=[]),
                patch("server.modules.project_container.sync_container") as sync,
                patch("server.modules.derived_audio_preparation.refresh_overlap_preparation") as refresh,
            ):
                saved = project_repository.write_project(workspace.default_project())

            sync.assert_called_once_with(container, root, include_derived_audio=False)
            refresh.assert_called_once_with(saved)

    def test_windows_atomic_write_does_not_open_the_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "nested" / "project.json"
            real_open = project_repository.os.open

            def guarded_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
                if Path(path).is_dir():  # type: ignore[arg-type]
                    raise PermissionError("Windows cannot open directories")
                return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

            with (
                patch.object(project_repository, "os", SimpleNamespace(
                    name="nt", open=guarded_open, fdopen=project_repository.os.fdopen,
                    fsync=project_repository.os.fsync, replace=project_repository.os.replace,
                )),
            ):
                project_repository._atomic_write(target, b'{"saved": true}\n')
            self.assertEqual(target.read_bytes(), b'{"saved": true}\n')
            self.assertEqual(list(target.parent.glob(".project.json.*.tmp")), [])

    def test_same_revision_concurrent_replacements_have_one_winner_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project_file = root / "project.json"
            with (
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(project_repository, "resolved_project_characters", side_effect=lambda value: value),
                patch("server.modules.project_pronunciation_snapshot.project_pronunciation_snapshot", return_value=[]),
            ):
                initial = project_repository.write_project(workspace.default_project())
                barrier = threading.Barrier(2)
                outcomes: list[str] = []

                def save(title: str) -> None:
                    candidate = copy.deepcopy(initial)
                    candidate["title"] = title
                    barrier.wait()
                    try:
                        project_repository.write_project(candidate, expected_revision=initial["revision"])
                        outcomes.append("saved")
                    except HTTPException as error:
                        outcomes.append(str(error.detail["code"]))

                threads = [threading.Thread(target=save, args=(title,)) for title in ("A", "B")]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()

            self.assertCountEqual(outcomes, ["saved", "project_revision_conflict"])
            self.assertIn(json.loads(project_file.read_text(encoding="utf-8"))["title"], {"A", "B"})
            self.assertEqual(list(root.glob(".project.json.*.tmp")), [])


if __name__ == "__main__":
    unittest.main()

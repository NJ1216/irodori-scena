from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from server.modules import project_container, workspace
from tools.migrate_scena_projects import convert


class MigrateScenaProjectsTests(unittest.TestCase):
    def test_converts_without_modifying_source_and_reports_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "legacy.scena"
            source.mkdir()
            project_bytes = json.dumps(workspace.default_project(), ensure_ascii=False).encode()
            (source / "project.json").write_bytes(project_bytes)
            (source / "media/takes").mkdir(parents=True)
            (source / "media/takes/take.wav").write_bytes(b"take")
            (source / "media/exports").mkdir()
            (source / "media/exports/final.wav").write_bytes(b"export")
            destination = root / "migrated.scena"

            included, excluded, excluded_size, _stored_size = convert(source, destination)
            extracted = root / "extracted"
            project_container.extract_container(destination, extracted)

            self.assertEqual((source / "project.json").read_bytes(), project_bytes)
            self.assertEqual((extracted / "media/takes/take.wav").read_bytes(), b"take")
            self.assertFalse((extracted / "media/exports").exists())
            self.assertEqual((included, excluded, excluded_size), (2, 1, 6))


if __name__ == "__main__":
    unittest.main()

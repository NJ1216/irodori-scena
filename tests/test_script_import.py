from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app import app, default_project


class ScriptImportTests(unittest.TestCase):
    def test_import_appends_lines_to_an_empty_scene(self) -> None:
        project = default_project()
        project["characters"] = [{"id": "riri", "name": "Riri"}]
        project["scenes"][0]["lines"] = []
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.project_repository.write_project", side_effect=lambda value: value) as write_project,
        ):
            response = TestClient(app).post(
                "/api/project/import-script",
                json={"lines": [{"character_id": "riri", "text": "こんにちは。"}]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scenes"][0]["lines"][0]["characterId"], "riri")
        self.assertEqual(response.json()["scenes"][0]["lines"][0]["text"], "こんにちは。")
        write_project.assert_called_once()

    def test_import_rejects_a_character_that_is_not_registered(self) -> None:
        project = default_project()
        with patch("server.modules.project_repository.read_project", return_value=project):
            response = TestClient(app).post(
                "/api/project/import-script",
                json={"lines": [{"character_id": "missing", "text": "こんにちは。"}]},
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()

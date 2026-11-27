from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app
from server.modules import project_patch_service


class ProjectPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {
            "version": 1,
            "revision": 4,
            "title": "Before",
            "characters": [],
            "scenes": [{"id": "scene", "lines": [{"id": "line", "text": "old", "selectedTakeId": "take"}]}],
            "settings": {"speechRate": 1.2},
        }

    def _write(self, project, **_kwargs):
        project["revision"] += 1
        self.project = project

    def test_metadata_patch_updates_only_allowed_fields_and_revision(self) -> None:
        with (
            patch("server.modules.project_repository.read_project", side_effect=lambda: self.project),
            patch("server.modules.project_repository.write_project", side_effect=self._write),
        ):
            revision = project_patch_service.apply_project_patch("metadata", 4, {"title": "After"})
        self.assertEqual((revision, self.project["title"]), (5, "After"))

    def test_stale_revision_is_not_written(self) -> None:
        with (
            patch("server.modules.project_repository.read_project", return_value=self.project),
            patch("server.modules.project_repository.write_project") as write,
        ):
            self.assertIsNone(project_patch_service.apply_project_patch("settings", 3, {"speechRate": 1.1}))
        write.assert_not_called()

    def test_line_render_change_clears_selected_take(self) -> None:
        with (
            patch("server.modules.project_repository.read_project", side_effect=lambda: self.project),
            patch("server.modules.project_repository.write_project", side_effect=self._write),
        ):
            project_patch_service.apply_project_patch("line", 4, {"text": "new"}, "line")
        self.assertEqual(self.project["scenes"][0]["lines"][0]["selectedTakeId"], None)

    def test_unknown_field_is_rejected(self) -> None:
        with patch("server.modules.project_repository.read_project", return_value=self.project):
            with self.assertRaises(HTTPException) as raised:
                project_patch_service.apply_project_patch("metadata", 4, {"characters": []})
        self.assertEqual(raised.exception.status_code, 422)

    def test_http_conflict_returns_current_revision(self) -> None:
        with patch("server.modules.project_patch_service.apply_project_patch", return_value=None), patch(
            "server.modules.project_repository.read_project", return_value=self.project
        ):
            from fastapi.testclient import TestClient

            response = TestClient(app).patch(
                "/api/project/metadata", json={"baseRevision": 3, "changes": {"title": "After"}}
            )
        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "project_revision_conflict")
        self.assertEqual(detail["currentRevision"], 4)
        self.assertEqual(detail["currentProject"], self.project)

    def test_http_request_rejects_unknown_top_level_fields(self) -> None:
        from fastapi.testclient import TestClient

        response = TestClient(app).patch(
            "/api/project/metadata",
            json={"baseRevision": 4, "changes": {"title": "After"}, "unknown": True},
        )
        self.assertEqual(response.status_code, 422)

    def test_character_order_requires_an_exact_permutation_and_increments_revision(self) -> None:
        self.project["characters"] = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        with (
            patch("server.modules.project_repository.read_project", side_effect=lambda: self.project),
            patch("server.modules.project_repository.write_project", side_effect=self._write) as write,
        ):
            updated = project_patch_service.apply_character_order(4, ["c", "a", "b"])
            self.assertEqual([item["id"] for item in updated["characters"]], ["c", "a", "b"])
            self.assertEqual(updated["revision"], 5)
            with self.assertRaises(HTTPException):
                project_patch_service.apply_character_order(5, ["a", "a", "c"])
            with self.assertRaises(HTTPException):
                project_patch_service.apply_character_order(5, ["a", "b", "unknown"])
        self.assertEqual(write.call_count, 1)
        self.assertTrue(write.call_args.kwargs["project_only"])

    def test_character_order_uses_the_shared_revision_conflict(self) -> None:
        from fastapi.testclient import TestClient

        with patch("server.modules.project_patch_service.apply_character_order", return_value=None), patch(
            "server.modules.project_repository.read_project", return_value=self.project
        ):
            response = TestClient(app).patch("/api/characters/order", json={"baseRevision": 3, "characterIds": []})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "project_revision_conflict")


if __name__ == "__main__":
    unittest.main()

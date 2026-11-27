from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from server.app import apply_global_cast_updates, global_cast_update_candidates


class GlobalCastUpdateTests(unittest.TestCase):
    def test_detects_same_id_when_the_global_cast_has_changed(self) -> None:
        project = {"characters": [{"id": "cast-1", "name": "旧名", "scope": "project", "audioHash": "old"}]}
        global_character = {"id": "cast-1", "name": "新名", "audioHash": "new"}
        with patch("server.modules.project_repository.read_global_characters", return_value=[global_character]):
            self.assertEqual(global_cast_update_candidates(project), [{"id": "cast-1", "name": "新名"}])

    def test_detects_missing_project_avatar_even_when_other_content_matches(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            global_avatar = root / "global" / "characters" / "cast-1" / "avatar-thumbnail.png"
            global_avatar.parent.mkdir(parents=True)
            global_avatar.write_bytes(b"global avatar")
            character = {
                "id": "cast-1",
                "name": "同じ名前",
                "audioHash": "same",
                "avatarThumbnailUrl": "/media/characters/cast-1/avatar-thumbnail.png",
            }
            global_character = {
                **character,
                "scope": "global",
                "avatarThumbnailUrl": "/global-media/characters/cast-1/avatar-thumbnail.png",
            }
            with (
                patch("server.modules.project_repository.read_global_characters", return_value=[global_character]),
                patch("server.modules.constants.MEDIA_ROOT", root / "project"),
                patch("server.modules.constants.GLOBAL_MEDIA_ROOT", root / "global"),
            ):
                self.assertEqual(global_cast_update_candidates({"characters": [character]}), [{"id": "cast-1", "name": "同じ名前"}])

    def test_applies_global_cast_as_a_portable_project_snapshot(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "global" / "characters" / "cast-1" / "reference.wav"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"RIFF global reference")
            project: dict[str, object] = {
                "characters": [{"id": "cast-1", "name": "旧名", "scope": "project", "audioHash": "old"}],
            }
            global_character = {"id": "cast-1", "name": "新名", "referenceFile": str(source), "audioHash": "new"}
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.read_global_characters", return_value=[global_character]),
                patch("server.modules.project_repository.write_project") as write_project,
                patch("server.modules.constants.MEDIA_ROOT", root / "project" / "media"),
            ):
                updated = apply_global_cast_updates(["cast-1"])

            snapshot = updated["characters"][0]
            self.assertEqual(snapshot["name"], "新名")
            self.assertEqual(snapshot["scope"], "project")
            self.assertTrue((root / "project" / "media" / "characters" / "cast-1" / "reference.wav").is_file())
            write_project.assert_called_once_with(project)

    def test_applies_global_avatar_without_changing_its_source(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            global_root = root / "global"
            source_root = global_root / "characters" / "cast-1"
            source_root.mkdir(parents=True)
            reference = source_root / "reference.wav"
            original = source_root / "avatar-original.png"
            thumbnail = source_root / "avatar-thumbnail.png"
            reference.write_bytes(b"RIFF global reference")
            original.write_bytes(b"original")
            thumbnail.write_bytes(b"thumbnail")
            project: dict[str, object] = {"characters": [{"id": "cast-1", "scope": "project"}]}
            global_character = {
                "id": "cast-1",
                "name": "新名",
                "referenceFile": str(reference),
                "avatarOriginalUrl": "/global-media/characters/cast-1/avatar-original.png",
                "avatarThumbnailUrl": "/global-media/characters/cast-1/avatar-thumbnail.png",
                "avatarUrl": "/global-media/characters/cast-1/avatar-thumbnail.png",
            }
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.read_global_characters", return_value=[global_character]),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.constants.GLOBAL_MEDIA_ROOT", global_root),
                patch("server.modules.constants.MEDIA_ROOT", root / "project" / "media"),
            ):
                updated = apply_global_cast_updates(["cast-1"])

            snapshot = updated["characters"][0]
            self.assertEqual(original.read_bytes(), b"original")
            self.assertEqual(thumbnail.read_bytes(), b"thumbnail")
            self.assertEqual(snapshot["avatarOriginalUrl"], "/media/characters/cast-1/avatar-original.png")
            self.assertEqual(snapshot["avatarThumbnailUrl"], "/media/characters/cast-1/avatar-thumbnail.png")

    def test_rejects_missing_global_avatar_before_changing_project(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "global" / "characters" / "cast-1" / "reference.wav"
            reference.parent.mkdir(parents=True)
            reference.write_bytes(b"RIFF global reference")
            project: dict[str, object] = {
                "characters": [
                    {
                        "id": "cast-1",
                        "scope": "project",
                        "avatarUrl": "/media/characters/cast-1/avatar-thumbnail.png",
                    }
                ]
            }
            global_character = {
                "id": "cast-1",
                "name": "新名",
                "referenceFile": str(reference),
                "avatarUrl": "/global-media/characters/cast-1/avatar-thumbnail.png",
            }
            project_media = root / "project" / "media"
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.read_global_characters", return_value=[global_character]),
                patch("server.modules.project_repository.write_project") as write_project,
                patch("server.modules.constants.GLOBAL_MEDIA_ROOT", root / "global"),
                patch("server.modules.constants.MEDIA_ROOT", project_media),
                self.assertRaisesRegex(HTTPException, "画像ファイルが見つかりません"),
            ):
                apply_global_cast_updates(["cast-1"])

            write_project.assert_not_called()
            self.assertFalse(project_media.exists())
            self.assertEqual(project["characters"][0]["avatarUrl"], "/media/characters/cast-1/avatar-thumbnail.png")

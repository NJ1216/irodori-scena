from __future__ import annotations

import scena_test_isolation  # noqa: F401
import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.app import UpdateCharacterAvatarRequest, update_character_avatar


PNG = b"\x89PNG\r\n\x1a\nthumbnail"
JPEG = b"\xff\xd8\xfforiginal"


def data_url(content: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(content).decode()}"


class CharacterAvatarTests(unittest.TestCase):
    def test_avatar_keeps_original_and_189px_thumbnail_as_separate_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project: dict[str, object] = {
                "characters": [{"id": "cast-1", "name": "彩", "scope": "project"}],
            }
            request = UpdateCharacterAvatarRequest(
                original_image_base64=data_url(JPEG, "image/jpeg"),
                thumbnail_image_base64=data_url(PNG, "image/png"),
            )
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project") as write_project,
                patch("server.modules.project_repository.project_character_matches_global", return_value=False),
                patch("server.modules.constants.MEDIA_ROOT", root / "media"),
            ):
                character = update_character_avatar("cast-1", request)

            avatar_root = root / "media" / "characters" / "cast-1"
            self.assertEqual((avatar_root / "avatar-original.jpg").read_bytes(), JPEG)
            self.assertEqual((avatar_root / "avatar-thumbnail.png").read_bytes(), PNG)
            self.assertEqual(character["avatarOriginalUrl"], "/media/characters/cast-1/avatar-original.jpg")
            self.assertEqual(character["avatarThumbnailUrl"], "/media/characters/cast-1/avatar-thumbnail.png")
            self.assertEqual(character["avatarUrl"], character["avatarThumbnailUrl"])
            write_project.assert_called_once_with(project)

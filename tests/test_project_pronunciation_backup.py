from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.app import (
    UpdateCharacterRequest,
    project_backup_snapshot,
    project_character_matches_global,
    project_pronunciation_snapshot,
    resolved_project_characters,
    update_character,
    read_pronunciation_dictionary,
    reconcile_cast_pronunciations,
)


class ProjectPronunciationBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = {
            "characters": [
                {"id": "cast-a", "name": "彩", "profile": "明るい学生", "profileDetails": {"role": "学生"}},
                {"id": "cast-b", "name": "理央", "profile": "不参加", "profileDetails": {}},
            ],
            "scenes": [{"lines": [{"characterId": "cast-a", "text": "彩です。"}]}],
        }
        self.entries = [
            {"id": "manual-1", "source": "manual", "term": "SCENA", "reading": "しーな"},
            {"id": "cast-a-1", "source": "cast", "characterId": "cast-a", "term": "彩", "reading": "あや"},
            {"id": "cast-b-1", "source": "cast", "characterId": "cast-b", "term": "理央", "reading": "りお"},
        ]

    def test_backup_keeps_participating_profiles_and_relevant_dictionary_entries(self) -> None:
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=self.entries):
            snapshot = project_backup_snapshot(self.project)
        self.assertEqual([character["id"] for character in snapshot["characters"]], ["cast-a"])
        self.assertEqual([entry["id"] for entry in snapshot["pronunciationDictionary"]], ["cast-a-1"])

    def test_snapshot_does_not_capture_unused_global_manual_entries(self) -> None:
        with patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=self.entries):
            snapshot = project_pronunciation_snapshot({"scenes": []})
        self.assertEqual(snapshot, [])

    def test_saved_project_profile_shadows_an_updated_global_character_without_overwriting_it(self) -> None:
        saved = {"id": "cast-a", "name": "彩", "profile": "保存時のプロフィール"}
        global_character = {"id": "cast-a", "name": "彩", "profile": "最新のプロフィール"}
        with patch("server.modules.project_repository.read_global_characters", return_value=[global_character]):
            resolved = resolved_project_characters({"characters": [saved]})
        self.assertEqual(resolved["characters"][0]["profile"], "保存時のプロフィール")
        self.assertEqual(global_character["profile"], "最新のプロフィール")

    def test_matching_saved_character_is_eligible_for_global_edits(self) -> None:
        saved = {"id": "cast-a", "name": "彩", "profile": "同じプロフィール", "audioHash": "audio"}
        with patch("server.modules.project_repository.read_global_characters", return_value=[dict(saved)]):
            self.assertTrue(project_character_matches_global(saved))
        with patch(
            "server.modules.project_repository.read_global_characters",
            return_value=[{**saved, "profile": "更新済みプロフィール"}],
        ):
            self.assertFalse(project_character_matches_global(saved))

    def test_editing_a_matching_saved_character_updates_global_and_project_snapshot(self) -> None:
        saved = {"id": "cast-a", "name": "彩", "profile": "同じプロフィール", "imagePrompt": "old prompt", "audioHash": "audio", "scope": "project"}
        project = {"characters": [saved]}
        preferences = {"outfit": "ブレザー制服", "height": "165cm"}
        request = UpdateCharacterRequest(name="彩", profile="更新後のプロフィール", voice_keywords="自然な声", image_prompt="new prompt", image_prompt_preferences=preferences)
        with (
            patch("server.modules.project_repository.read_global_characters", return_value=[dict(saved)]),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.inference.find_character", return_value=saved),
            patch("server.modules.project_repository.write_global_characters") as write_global,
            patch("server.modules.project_repository.write_project") as write_project,
            patch("server.modules.pronunciation_dictionary.sync_character_pronunciations"),
        ):
            update_character("cast-a", request)
        self.assertEqual(write_global.call_args.args[0][0]["profile"], "更新後のプロフィール")
        self.assertEqual(write_global.call_args.args[0][0]["imagePrompt"], "new prompt")
        self.assertEqual(write_global.call_args.args[0][0]["imagePromptPreferences"]["outfit"], "ブレザー制服")
        self.assertEqual(saved["imagePromptPreferences"]["height"], "165cm")
        write_project.assert_called_once_with(project)

    def test_renaming_character_replaces_stale_cast_dictionary_terms(self) -> None:
        character = {
            "id": "cast-a",
            "name": "旧姓 旧名",
            "profile": "",
            "profileDetails": {
                "familyName": "旧姓",
                "familyNameKana": "きゅうせい",
                "givenName": "旧名",
                "givenNameKana": "きゅうめい",
            },
        }
        project = {"characters": [character]}
        request = UpdateCharacterRequest(
            name="白凪 芳祈",
            profile="",
            voice_keywords="",
            profile_details={
                "familyName": "白凪",
                "familyNameKana": "しらなぎ",
                "givenName": "芳祈",
                "givenNameKana": "よしき",
            },
        )
        with (
            TemporaryDirectory() as directory,
            patch("server.modules.constants.DATA_ROOT", Path(directory)),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.project_repository.read_global_characters", return_value=[]),
            patch("server.modules.project_repository.project_character_matches_global", return_value=False),
            patch("server.modules.project_repository.write_project"),
        ):
            reconcile_cast_pronunciations([character])
            update_character("cast-a", request)
            entries = read_pronunciation_dictionary()

        terms = {entry["term"]: entry["reading"] for entry in entries}
        self.assertEqual(terms, {"白凪": "しらなぎ", "芳祈": "よしき"})

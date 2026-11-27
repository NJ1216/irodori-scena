from __future__ import annotations

import scena_test_isolation  # noqa: F401
import base64
import json
import unittest
from fastapi import HTTPException
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.app import GenerateLineRequest, GenerationCancelled, UpdateCharacterAvatarRequest
from server.modules import character_avatar_routes, character_routes, constants, project_repository, script_routes


PNG = b"\x89PNG\r\n\x1a\nthumbnail"
JPEG = b"\xff\xd8\xfforiginal"


def data_url(content: bytes, media_type: str) -> str:
    return f"data:{media_type};base64,{base64.b64encode(content).decode()}"


class DestructiveMutationSafetyTests(unittest.TestCase):
    def test_auto_render_cancel_targets_only_the_active_line(self) -> None:
        request = GenerateLineRequest(quality="fast", interruptible=True)
        should_cancel = script_routes._auto_render_cancelled(request, "line-1")
        try:
            self.assertEqual(script_routes.cancel_auto_render(script_routes.deps.CancelAutoRenderRequest(lineId="line-2")), {"cancelled": False})
            self.assertFalse(should_cancel())
            self.assertEqual(script_routes.cancel_auto_render(script_routes.deps.CancelAutoRenderRequest(lineId="line-1")), {"cancelled": True})
            self.assertTrue(should_cancel())
        finally:
            script_routes._finish_auto_render(request, "line-1")

    def test_regeneration_can_target_previous_take_after_line_edit_clears_selection(self) -> None:
        fixture = Path(__file__).with_name("fixtures") / "project-contract.json"
        project = json.loads(fixture.read_text(encoding="utf-8"))
        line = project["scenes"][0]["lines"][0]
        take_id = line["selectedTakeId"]
        line["selectedTakeId"] = None
        replacement = {**line["takes"][0], "id": take_id}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", root / "project.json"),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(project_repository, "resolved_project_characters", side_effect=lambda value: value),
                patch("server.modules.project_pronunciation_snapshot.project_pronunciation_snapshot", return_value=[]),
                patch("server.modules.export_service.require_tts_available"),
                patch.object(script_routes, "create_line_take", return_value=replacement),
            ):
                project_repository.write_project(project)
                script_routes.regenerate_line(line["id"], GenerateLineRequest(quality="fast", targetTakeId=take_id))
                saved = project_repository.read_project()["scenes"][0]["lines"][0]
        self.assertEqual(saved["selectedTakeId"], take_id)
        self.assertEqual(len(saved["takes"]), 1)

    def test_generation_responses_report_the_persisted_project_revision(self) -> None:
        generated = {
            "id": "take-2",
            "audioUrl": "/media/takes/line-1/take-2.wav",
            "seed": 2,
            "quality": "fast",
            "stageDirection": "",
            "createdAt": 2,
        }
        fixture = Path(__file__).with_name("fixtures") / "project-contract.json"
        project = json.loads(fixture.read_text(encoding="utf-8"))
        line_id = project["scenes"][0]["lines"][0]["id"]
        generated["audioUrl"] = f"/media/takes/{line_id}/take-2.wav"

        with TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", root / "project.json"),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(project_repository, "resolved_project_characters", side_effect=lambda value: value),
                patch("server.modules.project_pronunciation_snapshot.project_pronunciation_snapshot", return_value=[]),
                patch("server.modules.export_service.require_tts_available"),
                patch.object(script_routes, "create_line_take", return_value=generated),
            ):
                initial = project_repository.write_project(project)
                appended = script_routes.generate_line(line_id, GenerateLineRequest(quality="fast"))
                replaced = script_routes.regenerate_line(line_id, GenerateLineRequest(quality="fast"))
                persisted = project_repository.read_project()

        self.assertEqual(appended, {"take": generated, "projectRevision": initial["revision"] + 1})
        self.assertEqual(replaced, {"take": generated, "projectRevision": initial["revision"] + 2})
        self.assertEqual(persisted["revision"], replaced["projectRevision"])

    def test_line_delete_keeps_take_when_project_write_fails(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            take = media / "takes" / "line-1" / "take.wav"
            take.parent.mkdir(parents=True)
            take.write_bytes(b"original")
            project = {"scenes": [{"id": "scene-1", "lines": [{"id": "line-1"}]}]}
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")),
                patch("server.modules.dialogue_cues.normalize_scene_cues"),
                patch("server.modules.constants.MEDIA_ROOT", media),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                script_routes.delete_line("scene-1", "line-1")
            self.assertEqual(take.read_bytes(), b"original")

    def test_reference_replacement_restores_previous_wav_when_metadata_fails(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            target = media / "characters" / "cast-1" / "reference.wav"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"old reference")
            character = {"id": "cast-1", "scope": "project", "referenceFile": str(target)}
            project = {"characters": [character], "scenes": []}
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")),
                patch("server.modules.project_repository.project_character_matches_global", return_value=False),
                patch("server.modules.constants.MEDIA_ROOT", media),
                patch("server.modules.common.new_id", side_effect=["update", "rollback"]),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                character_routes._apply_reference_audio("cast-1", b"new reference")
            self.assertEqual(target.read_bytes(), b"old reference")

    def test_take_regeneration_restores_previous_wav_when_metadata_fails(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            target = media / "takes" / "line-1" / "take-1.wav"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"old take")
            line = {"id": "line-1", "selectedTakeId": "take-1", "takes": [{"id": "take-1"}]}
            project = {"scenes": [{"lines": [line]}]}

            def replace_take(*_args, **_kwargs):
                target.write_bytes(b"new take")
                return {"id": "take-1", "audioUrl": "/media/takes/line-1/take-1.wav"}

            with (
                patch("server.modules.export_service.require_tts_available"),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")),
                patch("server.modules.inference.find_line", return_value=({"lines": [line]}, line)),
                patch.object(script_routes, "create_line_take", side_effect=replace_take),
                patch("server.modules.constants.MEDIA_ROOT", media),
                patch("server.modules.common.new_id", return_value="rollback"),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                script_routes.regenerate_line("line-1", GenerateLineRequest(quality="fast"))
            self.assertEqual(target.read_bytes(), b"old take")

    def test_character_delete_keeps_reference_when_metadata_fails(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            target = media / "characters" / "cast-1" / "reference.wav"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"reference")
            character = {"id": "cast-1", "scope": "project"}
            project = {"id": "project-1", "characters": [character], "scenes": []}
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")),
                patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]),
                patch("server.modules.pronunciation_dictionary.remove_character_pronunciations"),
                patch("server.modules.pronunciation_dictionary.write_pronunciation_dictionary"),
                patch("server.modules.constants.MEDIA_ROOT", media),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                character_routes.delete_character("cast-1")
            self.assertEqual(target.read_bytes(), b"reference")

    def test_character_delete_removes_matching_global_library_entry(self) -> None:
        character = {"id": "cast-1", "scope": "project"}
        project = {"id": "project-1", "characters": [character], "scenes": []}
        with (
            TemporaryDirectory() as directory,
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.project_repository.project_character_matches_global", return_value=True),
            patch("server.modules.project_repository.read_global_characters", return_value=[character]),
            patch("server.modules.project_repository.write_global_characters") as write_global,
            patch("server.modules.project_repository.write_project"),
            patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]),
            patch("server.modules.pronunciation_dictionary.remove_character_pronunciations"),
            patch("server.modules.cast_context_cache.delete_cast_context") as delete_context,
            patch("server.modules.constants.MEDIA_ROOT", Path(directory) / "project-media"),
            patch("server.modules.constants.GLOBAL_MEDIA_ROOT", Path(directory) / "global-media"),
        ):
            character_routes.delete_character("cast-1")

        write_global.assert_called_once_with([])
        delete_context.assert_called_once_with("global", "cast-1", "project-1")

    def test_interruptible_manual_regeneration_restores_previous_wav(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            target = media / "takes" / "line-1" / "take-1.wav"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"old take")
            line = {"id": "line-1", "selectedTakeId": "take-1", "takes": [{"id": "take-1"}]}
            project = {"scenes": [{"lines": [line]}]}

            def cancelled_take(*_args, **_kwargs):
                target.write_bytes(b"partial take")
                raise GenerationCancelled("cancelled")

            with (
                patch("server.modules.export_service.require_tts_available"),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.inference.find_line", return_value=({"lines": [line]}, line)),
                patch.object(script_routes, "create_line_take", side_effect=cancelled_take),
                patch("server.modules.constants.MEDIA_ROOT", media),
                patch("server.modules.common.new_id", return_value="rollback"),
                self.assertRaises(HTTPException),
            ):
                script_routes.regenerate_line("line-1", GenerateLineRequest(quality="fast", interruptible=True))
            self.assertEqual(target.read_bytes(), b"old take")

    def test_avatar_replacement_restores_previous_files_when_metadata_fails(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            avatar_root = media / "characters" / "cast-1"
            avatar_root.mkdir(parents=True)
            original, thumbnail = avatar_root / "avatar-original.png", avatar_root / "avatar-thumbnail.png"
            original.write_bytes(b"old original")
            thumbnail.write_bytes(b"old thumbnail")
            project = {"characters": [{"id": "cast-1", "scope": "project"}]}
            request = UpdateCharacterAvatarRequest(
                original_image_base64=data_url(JPEG, "image/jpeg"),
                thumbnail_image_base64=data_url(PNG, "image/png"),
            )
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")),
                patch("server.modules.project_repository.project_character_matches_global", return_value=False),
                patch("server.modules.constants.MEDIA_ROOT", media),
                patch("server.modules.common.new_id", return_value="rollback"),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                character_avatar_routes.update_character_avatar("cast-1", request)
            self.assertEqual(original.read_bytes(), b"old original")
            self.assertEqual(thumbnail.read_bytes(), b"old thumbnail")
            self.assertFalse((avatar_root / "avatar-original.jpg").exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import constants, script_routes, take_cleanup
from server.modules import history, history_targets


class TakeCleanupTests(unittest.TestCase):
    @staticmethod
    def _project() -> dict[str, object]:
        return {
            "scenes": [
                {
                    "lines": [
                        {
                            "takes": [{"id": "take-1", "audioUrl": "/media/takes/line/take.wav"}],
                            "selectedTakeId": "take-1",
                            "archivedTakes": [{"id": "old"}],
                        }
                    ]
                }
            ]
        }

    def test_stages_take_media_before_compact_save(self) -> None:
        with TemporaryDirectory() as raw:
            media = Path(raw) / "media"
            audio = media / "takes/line/take.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"wav")
            project = self._project()

            def save(value, **options):
                self.assertFalse((media / "takes").exists())
                self.assertEqual(options, {})
                return value

            with (
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.common.new_id", return_value="cleanup"),
                patch("server.modules.project_repository.write_project", side_effect=save),
            ):
                saved = take_cleanup.clear_project_takes(project)

            line = saved["scenes"][0]["lines"][0]
            self.assertEqual(line["takes"], [])
            self.assertIsNone(line["selectedTakeId"])
            self.assertNotIn("archivedTakes", line)
            self.assertFalse(audio.exists())

    def test_deferred_cleanup_keeps_staged_media_until_discarded(self) -> None:
        with TemporaryDirectory() as raw:
            media = Path(raw) / "media"
            audio = media / "takes/line/take.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"wav")
            deferred: list[Path] = []
            with (
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.common.new_id", return_value="cleanup"),
                patch("server.modules.project_repository.write_project", side_effect=lambda value, **_: value),
            ):
                take_cleanup.clear_project_takes(self._project(), deferred=deferred)
            self.assertFalse((media / "takes").exists())
            self.assertEqual(len(deferred), 1)
            self.assertTrue((deferred[0] / "line/take.wav").exists())
            take_cleanup.discard_staged_takes(deferred[0])
            self.assertFalse(deferred[0].exists())

    def test_restores_take_media_when_compact_save_fails(self) -> None:
        with TemporaryDirectory() as raw:
            media = Path(raw) / "media"
            audio = media / "takes/line/take.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"wav")

            with (
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.common.new_id", return_value="cleanup"),
                patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")),
                self.assertRaises(OSError),
            ):
                take_cleanup.clear_project_takes(self._project())

            self.assertEqual(audio.read_bytes(), b"wav")

    def test_clear_takes_route_uses_the_atomic_cleanup_service(self) -> None:
        project = self._project()
        saved = {"scenes": []}
        with (
            patch("server.modules.export_service.require_tts_available") as require_tts,
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.take_cleanup.clear_project_takes", return_value=saved) as clear,
        ):
            result = script_routes.clear_all_takes()

        require_tts.assert_called_once_with()
        clear.assert_called_once_with(project, deferred=[])
        self.assertIs(result, saved)

    def test_selected_cleanup_keeps_adopted_and_other_lines(self) -> None:
        with TemporaryDirectory() as raw:
            media = Path(raw) / "media"
            for name in ("keep", "unused", "other"):
                path = media / f"takes/{name}/{name}.wav"
                path.parent.mkdir(parents=True)
                path.write_bytes(name.encode())
            project = {"scenes": [{"lines": [
                {"id": "target", "takes": [
                    {"id": "keep", "audioUrl": "/media/takes/keep/keep.wav"},
                    {"id": "unused", "audioUrl": "/media/takes/unused/unused.wav"},
                ], "selectedTakeId": "keep"},
                {"id": "other", "takes": [{"id": "other", "audioUrl": "/media/takes/other/other.wav"}], "selectedTakeId": "other"},
            ]}]}
            with (patch.object(constants, "MEDIA_ROOT", media), patch("server.modules.common.new_id", return_value="cleanup"),
                  patch("server.modules.project_repository.write_project", side_effect=lambda value: value)):
                saved = take_cleanup.cleanup_line_takes(project, ["target"], "unselected")
            self.assertEqual([take["id"] for take in saved["scenes"][0]["lines"][0]["takes"]], ["keep"])
            self.assertTrue((media / "takes/keep/keep.wav").exists())
            self.assertFalse((media / "takes/unused/unused.wav").exists())
            self.assertTrue((media / "takes/other/other.wav").exists())

    def test_selected_cleanup_restores_media_on_failed_save(self) -> None:
        with TemporaryDirectory() as raw:
            media = Path(raw) / "media"
            audio = media / "takes/target/take.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"wav")
            project = {"scenes": [{"lines": [{"id": "target", "takes": [{"id": "take", "audioUrl": "/media/takes/target/take.wav"}], "selectedTakeId": "take"}]}]}
            with (patch.object(constants, "MEDIA_ROOT", media), patch("server.modules.common.new_id", return_value="cleanup"),
                  patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")), self.assertRaises(OSError)):
                take_cleanup.cleanup_line_takes(project, ["target"], "all")
            self.assertEqual(audio.read_bytes(), b"wav")

    def test_selected_cleanup_has_one_script_undo_media_boundary(self) -> None:
        async def payload():
            return {"line_ids": ["first", "second"], "mode": "all"}

        request = SimpleNamespace(method="POST", url=SimpleNamespace(path="/api/lines/cleanup-takes"), json=payload)
        self.assertEqual(history._scope_for(request.url.path, request.method), "script")
        self.assertTrue(history._mutates_media(request.url.path, request.method))
        self.assertEqual(asyncio.run(history_targets.batch_delete_media_targets(request)), ["takes/first", "takes/second"])


if __name__ == "__main__":
    unittest.main()

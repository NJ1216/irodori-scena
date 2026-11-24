from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

import server.app  # noqa: F401
from starlette.requests import Request
from starlette.responses import Response
from server.modules import constants, history, project_container


class HistoryMediaTargetTests(unittest.TestCase):
    def test_auto_render_after_line_delete_undoes_with_the_delete(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            deleted_take = media / "takes/deleted/old.wav"
            generated_take = media / "takes/other/new.wav"
            deleted_take.parent.mkdir(parents=True)
            deleted_take.write_bytes(b"old")
            original = {"revision": 1, "scenes": [{"lines": [
                {"id": "deleted", "takes": [{"audioUrl": "/media/takes/deleted/old.wav"}]},
                {"id": "other", "takes": []},
            ]}]}
            project_file.write_text(json.dumps(original), encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
            ):
                history.begin_history_session()
                before_delete = history.capture_history_before("script", True, ["takes/deleted"])
                deleted = {"revision": 2, "scenes": [{"lines": [original["scenes"][0]["lines"][1]]}]}
                project_file.write_text(json.dumps(deleted), encoding="utf-8")
                deleted_take.unlink()
                history.commit_history("script", before_delete)
                before_generation = history.capture_history_before("script", True, ["takes/other"])
                generated_take.parent.mkdir(parents=True)
                generated_take.write_bytes(b"new")
                generated = {"revision": 3, "scenes": [{"lines": [{"id": "other", "takes": [{"audioUrl": "/media/takes/other/new.wav"}]}]}]}
                project_file.write_text(json.dumps(generated), encoding="utf-8")
                history.commit_history("script", before_generation, auto_render_base_revision=2)
                history.apply_history("script", "undo")
                restored = json.loads(project_file.read_text(encoding="utf-8"))
                self.assertEqual([line["id"] for line in restored["scenes"][0]["lines"]], ["deleted", "other"])
                self.assertEqual(deleted_take.read_bytes(), b"old")
                self.assertFalse(generated_take.exists())
                self.assertFalse(history.history_status("script")["canUndo"])
                history.apply_history("script", "redo")
                self.assertEqual([line["id"] for line in json.loads(project_file.read_text(encoding="utf-8"))["scenes"][0]["lines"]], ["other"])
                self.assertEqual(generated_take.read_bytes(), b"new")
                history.end_history_session()

    def test_metadata_history_uses_the_bounded_project_entry_sync(self) -> None:
        with TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "working"
            root.mkdir()
            project_file = root / "project.json"
            container = base / "project.scena"
            project_file.write_text('{"revision":1,"title":"before"}', encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", base / "data"),
                patch.object(constants, "ACTIVE_PROJECT_PATH", container),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
            ):
                history.begin_history_session()
                before = history.capture_history_before("script")
                project_file.write_text('{"revision":2,"title":"after"}', encoding="utf-8")
                history.commit_history("script", before)
                with (
                    patch.object(project_container, "sync_project_entry", return_value=True) as sync_project,
                    patch.object(project_container, "persist_active_container") as sync_all,
                ):
                    history.apply_history("script", "undo")
                sync_project.assert_called_once_with(container, root)
                sync_all.assert_not_called()
                history.end_history_session()

    def test_generated_take_history_is_persisted_to_the_active_container(self) -> None:
        with TemporaryDirectory() as raw:
            base = Path(raw)
            root = base / "working"
            project_file = root / "project.json"
            media = root / "media"
            container = base / "project.scena"
            old_take = media / "takes/line-1/old.wav"
            new_take = media / "takes/line-1/new.wav"
            old_take.parent.mkdir(parents=True)
            old_take.write_bytes(b"old audio")
            before_project = {
                "revision": 1,
                "scenes": [{"lines": [{"takes": [{"audioUrl": "/media/takes/line-1/old.wav"}]}]}],
            }
            after_project = {
                "revision": 2,
                "scenes": [
                    {
                        "lines": [
                            {
                                "takes": [
                                    {"audioUrl": "/media/takes/line-1/old.wav"},
                                    {"audioUrl": "/media/takes/line-1/new.wav"},
                                ]
                            }
                        ]
                    }
                ],
            }
            project_file.write_text(json.dumps(before_project), encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", base / "data"),
                patch.object(constants, "ACTIVE_PROJECT_PATH", container),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
            ):
                project_container.sync_container(container, root)
                history.begin_history_session()
                before = history.capture_history_before("script", True, ["takes/line-1"])
                new_take.write_bytes(b"new audio")
                project_file.write_text(json.dumps(after_project), encoding="utf-8")
                project_container.sync_container(container, root)
                history.commit_history("script", before)

                with patch.object(project_container, "_compressed_copy", wraps=project_container._compressed_copy) as compressed:
                    history.apply_history("script", "undo")
                self.assertEqual({call.args[0].name for call in compressed.call_args_list}, {"project.json", "old.wav"})

                reopened = base / "reopened"
                project_container.extract_container(container, reopened)
                self.assertEqual(json.loads((reopened / "project.json").read_text()), {**before_project, "revision": 3})
                self.assertEqual((reopened / "media/takes/line-1/old.wav").read_bytes(), b"old audio")
                self.assertFalse((reopened / "media/takes/line-1/new.wav").exists())

                history.apply_history("script", "redo")

                redone = base / "redone"
                project_container.extract_container(container, redone)
                self.assertEqual(json.loads((redone / "project.json").read_text()), {**after_project, "revision": 4})
                self.assertEqual((redone / "media/takes/line-1/new.wav").read_bytes(), b"new audio")
                history.end_history_session()

    def test_three_generated_lines_share_one_undo_and_restore_their_seeds(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            project_file = root / "project.json"
            media = root / "media"
            media.mkdir()
            group_id = str(uuid4())
            project = {"revision": 1, "takes": []}
            project_file.write_text(json.dumps(project), encoding="utf-8")
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
            ):
                history.begin_history_session()
                for index in range(3):
                    before = history.capture_history_before("script", True, [f"takes/line-{index}"])
                    take = media / f"takes/line-{index}/take.wav"
                    take.parent.mkdir(parents=True)
                    take.write_bytes(f"audio-{index}".encode())
                    project["revision"] += 1
                    project["takes"].append({"audioUrl": f"/media/takes/line-{index}/take.wav", "seed": 100 + index})
                    project_file.write_text(json.dumps(project), encoding="utf-8")
                    history.commit_history("script", before, generation_group_id=group_id)
                self.assertEqual(len(history._HISTORY["script"]), 1)
                self.assertEqual(
                    history._HISTORY["script"][0]["before"]["mediaTargets"],
                    ["takes/line-0", "takes/line-1", "takes/line-2"],
                )
                history.apply_history("script", "undo")
                self.assertEqual(json.loads(project_file.read_text())["takes"], [])
                self.assertFalse((media / "takes/line-2/take.wav").exists())
                history.apply_history("script", "redo")
                self.assertEqual([take["seed"] for take in json.loads(project_file.read_text())["takes"]], [100, 101, 102])
                self.assertEqual((media / "takes/line-2/take.wav").read_bytes(), b"audio-2")
                history.end_history_session()

    def test_generation_middleware_records_only_take_media(self) -> None:
        group_id = str(uuid4())

        async def exercise(path: str, method: str = "POST"):
            headers = [(b"x-scena-history-group", group_id.encode())] if method == "POST" else []
            request = Request({"type": "http", "method": method, "path": path, "headers": headers})

            async def call_next(_request):
                return Response(status_code=200)

            with (
                patch.object(history, "capture_history_before", return_value={"files": {}}) as capture,
                patch.object(history, "commit_history") as commit,
            ):
                await history.history_middleware(request, call_next)
                self.assertEqual(capture.call_args.args, ("script", True, ["takes/line-1"]))
                self.assertEqual(commit.call_args.args[-1], group_id if method == "POST" else None)

        asyncio.run(exercise("/api/lines/line-1/generate"))
        asyncio.run(exercise("/api/lines/line-1/regenerate"))
        asyncio.run(exercise("/api/lines/line-1/takes/take-1", "DELETE"))

    def test_scene_deletion_middleware_records_only_its_line_takes(self) -> None:
        request = Request({"type": "http", "method": "DELETE", "path": "/api/scenes/scene-one", "headers": []})

        async def call_next(_request):
            return Response(status_code=200)

        project = {"scenes": [{"id": "scene-one", "lines": [{"id": "line-1"}, {"id": "line-2"}]}]}
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch.object(history, "capture_history_before", return_value={"files": {}}) as capture,
            patch.object(history, "commit_history"),
        ):
            asyncio.run(history.history_middleware(request, call_next))
        self.assertEqual(capture.call_args.args, ("script", True, ["takes/line-1", "takes/line-2"]))

    def test_legacy_single_line_deletion_records_only_its_takes(self) -> None:
        request = Request({"type": "http", "method": "DELETE", "path": "/api/scenes/scene-one/lines/line-1", "headers": []})

        async def call_next(_request):
            return Response(status_code=200)

        with (
            patch.object(history, "capture_history_before", return_value={"files": {}}) as capture,
            patch.object(history, "commit_history"),
        ):
            asyncio.run(history.history_middleware(request, call_next))
        self.assertEqual(capture.call_args.args, ("script", True, ["takes/line-1"]))



async def _async_value(value):
    return value



if __name__ == "__main__":
    unittest.main()

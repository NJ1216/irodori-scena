from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from server.app import GenerationCancelled
from server.modules import export_service, pronunciation_dictionary
from server.registry import deps


class ExportCommitCancellationTests(unittest.TestCase):
    def test_cancel_while_waiting_for_commit_locks_discards_the_uncommitted_take(self) -> None:
        for lock in [deps.PROJECT_ROOT_LOCK, pronunciation_dictionary._dictionary_lock]:
            with self.subTest(lock=lock), TemporaryDirectory() as directory:
                project = {
                    "settings": {}, "characters": [{"id": "cast"}],
                    "scenes": [{"id": "scene", "lines": [{"id": "line", "text": "台詞", "characterId": "cast", "takes": [], "selectedTakeId": None}]}],
                }
                audio = Path(directory) / "take.wav"
                take = {"id": "take", "audioUrl": "/media/take.wav"}
                cancelled, committing = Event(), Event()
                commit = export_service._commit_export_take

                def render(*_args, **kwargs):
                    self.assertIsNone(kwargs.get("should_cancel"))
                    audio.write_bytes(b"completed synthesis")
                    return take

                def begin_commit(*args, **kwargs):
                    committing.set()
                    return commit(*args, **kwargs)

                with (
                    patch("server.modules.constants.MEDIA_ROOT", Path(directory)),
                    patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]),
                    patch("server.modules.project_repository.read_project", side_effect=lambda: deepcopy(project)),
                    patch("server.modules.project_repository.write_project") as write,
                    patch("server.modules.script_routes.create_line_take", side_effect=render),
                    patch.object(export_service, "_commit_export_take", side_effect=begin_commit),
                    ThreadPoolExecutor(max_workers=1) as pool,
                ):
                    with lock:
                        future = pool.submit(export_service.ensure_export_take, "line", "fast", should_cancel=cancelled.is_set)
                        self.assertTrue(committing.wait(timeout=2), "render did not reach the commit boundary")
                        cancelled.set()
                    with self.assertRaises(GenerationCancelled):
                        future.result(timeout=2)
                write.assert_not_called()
                self.assertFalse(audio.exists())


if __name__ == "__main__":
    unittest.main()

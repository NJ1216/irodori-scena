from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import constants, history
from server.modules.history_pending import PendingCaptures


class HistoryPendingBlobTests(unittest.TestCase):
    def test_in_flight_capture_survives_a_concurrent_commit_prune(self) -> None:
        with TemporaryDirectory() as raw:
            data_root = Path(raw) / "data"
            project_file = data_root / "project.json"
            data_root.mkdir()
            project_file.write_text(json.dumps({"revision": 1, "title": "a"}))
            with (
                patch.object(constants, "DATA_ROOT", data_root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", data_root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", data_root / "media"),
                patch.object(history, "_HISTORY", {"script": [], "characters": [], "pronunciation": []}),
                patch.object(history, "_CURSOR", {"script": 0, "characters": 0, "pronunciation": 0}),
                patch.object(history, "_ROOT", None),
                patch.object(history, "_PENDING", PendingCaptures()),
            ):
                # Request A (e.g. a long /generate) captured state "a" and is still running.
                before_a = history.capture_history_before("script")
                # State moves on, then request B commits, which prunes unreferenced blobs.
                project_file.write_text(json.dumps({"revision": 2, "title": "b"}))
                before_b = history.capture_history_before("script")
                project_file.write_text(json.dumps({"revision": 3, "title": "c"}))
                history.commit_history("script", before_b)
                history.release_history_capture(before_b)
                # Request A finishes afterwards and commits its own change.
                project_file.write_text(json.dumps({"revision": 4, "title": "d"}))
                history.commit_history("script", before_a)
                history.release_history_capture(before_a)

                self.assertEqual(history._PENDING.blobs, {})
                history.apply_history("script", "undo")
                self.assertEqual(json.loads(project_file.read_text())["title"], "a")

    def test_release_from_a_previous_session_does_not_touch_new_counts(self) -> None:
        pending = PendingCaptures()
        old = {"files": {"project.json": "shared"}}
        pending.hold(old)
        pending.reset()
        current = {"files": {"project.json": "shared"}}
        pending.hold(current)

        pending.release(old)
        self.assertEqual(pending.blobs, {"shared": 1})
        pending.release(current)
        self.assertEqual(pending.blobs, {})


if __name__ == "__main__":
    unittest.main()

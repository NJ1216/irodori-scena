from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import history


class HistorySessionCleanupTests(unittest.TestCase):
    def test_graceful_shutdown_removes_only_the_current_undo_session(self) -> None:
        with TemporaryDirectory() as raw:
            base = Path(raw)
            current = base / "current"
            other = base / "other"
            (current / "blobs").mkdir(parents=True)
            (current / "blobs/take").write_bytes(b"wav")
            other.mkdir()
            with patch.object(history, "_ROOT", current), patch.object(history, "_SESSION", "current"):
                history.end_history_session()

            self.assertFalse(current.exists())
            self.assertTrue(other.exists())
            self.assertIsNone(history._ROOT)


if __name__ == "__main__":
    unittest.main()

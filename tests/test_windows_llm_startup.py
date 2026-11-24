from __future__ import annotations

import unittest
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import project_routes


class WindowsLlmStartupTests(unittest.TestCase):
    def test_windows_startup_queues_background_tts(self) -> None:
        with patch.object(project_routes.os, "name", "nt"), patch(
            "server.modules.tts_runtime.start_tts_prepare"
        ) as prepare:
            project_routes._prepare_tts_when_eager()
        prepare.assert_called_once_with(startup=True)

    def test_non_windows_startup_retains_eager_tts_preparation(self) -> None:
        with patch.object(project_routes.os, "name", "posix"), patch(
            "server.modules.tts_runtime.start_tts_prepare"
        ) as prepare:
            project_routes._prepare_tts_when_eager()
        prepare.assert_called_once_with(startup=True)


if __name__ == "__main__":
    unittest.main()

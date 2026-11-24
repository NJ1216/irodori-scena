import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import model_runtime_jobs as jobs


class WindowsModelRuntimeStatusTests(unittest.TestCase):
    def test_reports_card_failure_instead_of_global_idle_and_recovers(self):
        card = {"id": "card", "runtimeId": "legacy", "localMetadata": {"format": "GGUF"}}
        failed = {"state": "failed", "message": "missing LICENSE"}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(jobs.sys, "platform", "win32"), \
                patch.object(jobs, "JOBS", {"card": failed}), \
                patch("server.modules.constants.LOCAL_LLM_ROOT", Path(directory)), \
                patch("server.modules.llama_cpp_runtime.selected_backend", return_value="cpu"), \
                patch("server.modules.llama_cpp_runtime.recommended_backend", return_value="cpu"), \
                patch("server.modules.llama_cpp_runtime.llama_cpp_runtime_status") as status:
            status.return_value = {"ready": False, "version": "test", "job": {"state": "idle"}}
            self.assertEqual(jobs.model_runtime_status(card)["job"], failed)
            self.assertEqual(jobs.model_runtime_status(card)["state"], "missing")
            status.return_value["ready"] = True
            self.assertEqual(jobs.model_runtime_status(card)["state"], "ready")
            self.assertIsNone(jobs.model_runtime_status({**card, "id": "other"})["job"])

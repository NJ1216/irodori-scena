import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from server import app as _app_module  # noqa: F401
from server.modules import tts_downloads as downloads
from server.app_deps import HTTPException


class TtsInstallCancellationTests(unittest.TestCase):
    def test_terminal_cancellation_preserves_result_and_allows_next_install(self):
        for terminal in ("complete", "failed", "cancelled"):
            with self.subTest(terminal=terminal):
                state = {"id": "finished", "state": terminal, "stage": terminal,
                         "error": "original failure" if terminal == "failed" else None}
                before = dict(state)
                cancel = threading.Event()
                with patch.object(downloads, "TTS_JOBS", {"finished": state}), \
                        patch.object(downloads, "TTS_CANCEL", {"finished": cancel}), \
                        patch.object(downloads, "ACTIVE_TTS_JOB", "finished"):
                    self.assertEqual(downloads.cancel_tts_install("finished"), before)
                    self.assertEqual(downloads.tts_install_status("finished"), before)
                    self.assertFalse(cancel.is_set())
                    next_job, _ = downloads._job("model", "next")
                    self.assertEqual(next_job["state"], "queued")

    def test_active_cancellation_is_idempotent_and_worker_publishes_terminal(self):
        state = {"id": "active", "state": "running", "stage": "environment"}
        cancel = threading.Event()
        with patch.object(downloads, "TTS_JOBS", {"active": state}), \
                patch.object(downloads, "TTS_CANCEL", {"active": cancel}), \
                patch.object(downloads, "_install_engine", side_effect=InterruptedError):
            self.assertEqual(downloads.cancel_tts_install("active")["state"], "cancelling")
            self.assertEqual(downloads.cancel_tts_install("active")["state"], "cancelling")
            self.assertTrue(cancel.is_set())
            downloads._run_install("engine", {}, state, cancel)
            self.assertEqual(downloads.tts_install_status("active")["state"], "cancelled")
            self.assertEqual(downloads.cancel_tts_install("active")["state"], "cancelled")

    def test_rollback_failure_reports_terminal_failure_and_releases_install_admission(self):
        for original in (InterruptedError(), OSError("model download failed")):
            for cleanup in (PermissionError("engine file locked"), HTTPException(409, "export still active")):
                with self.subTest(original=type(original).__name__, cleanup=type(cleanup).__name__):
                    state = {"id": "job", "state": "running", "stage": "model"}
                    dependencies = SimpleNamespace(
                        read_tts_registry=lambda: {"engines": []},
                        delete_tts_asset=lambda *_: (_ for _ in ()).throw(cleanup),
                    )
                    with patch.object(downloads, "deps", dependencies), \
                            patch.object(downloads, "_catalog_item", return_value={}), \
                            patch.object(downloads, "_install_engine"), \
                            patch.object(downloads, "_install_model", side_effect=original), \
                            patch.object(downloads, "TTS_JOBS", {"job": state}), \
                            patch.object(downloads, "TTS_CANCEL", {"job": threading.Event()}), \
                            patch.object(downloads, "ACTIVE_TTS_JOB", "job"):
                        downloads._run_install("model", {"supportedEngineIds": ["engine"], "displayName": "model"}, state, threading.Event())
                        self.assertEqual(state["state"], "failed")
                        self.assertEqual(state["stage"], "failed")
                        self.assertIsNone(state["currentFile"])
                        self.assertIn(getattr(cleanup, "detail", str(cleanup)), state["error"])
                        if not isinstance(original, InterruptedError):
                            self.assertIn(str(original), state["error"])
                        self.assertEqual(downloads._job("model", "retry")[0]["state"], "queued")

    def test_unexpected_install_error_reports_failure_and_releases_install_admission(self):
        # A programming error after the download (for example a TypeError while
        # registering the model) must not leave the job "running" forever and
        # block every later download with 409 until the app restarts.
        state = {"id": "job", "state": "running", "stage": "model"}
        dependencies = SimpleNamespace(read_tts_registry=lambda: {"engines": []})
        with patch.object(downloads, "deps", dependencies), \
                patch.object(downloads, "_install_model", side_effect=TypeError("'NoneType' object is not iterable")), \
                patch.object(downloads, "TTS_JOBS", {"job": state}), \
                patch.object(downloads, "TTS_CANCEL", {"job": threading.Event()}), \
                patch.object(downloads, "ACTIVE_TTS_JOB", "job"):
            downloads._run_install("model", {"displayName": "model"}, state, threading.Event())
            self.assertEqual((state["state"], state["stage"], state["errorCategory"]), ("failed", "failed", "installation"))
            self.assertIn("NoneType", state["error"])
            self.assertEqual(downloads._job("model", "retry")[0]["state"], "queued")

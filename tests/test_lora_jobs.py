from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException
from server.modules import constants, lora_jobs
from server.modules.lora_storage import owned_path, write_json
from server.lora_training_compat import compatible_trainer


class LoraJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(constants, "TTS_ASSETS_ROOT", self.root)
        self.patch.start()
        self.identifier = "a" * 32
        self.directory = owned_path("jobs", self.identifier)
        write_json(self.directory / "record.json", {"id": self.identifier, "status": "queued", "ownerPid": os.getpid(),
            "step": 0, "totalSteps": 3, "name": "test", "memo": "note", "adapterId": None})

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_restart_marks_interrupted_without_publishing_adapter(self):
        record = lora_jobs.read_record("jobs", self.identifier)
        record["ownerPid"] = -1
        write_json(self.directory / "record.json", record)
        result = lora_jobs.get_job(self.identifier)
        self.assertEqual(result["status"], "interrupted")
        self.assertIsNone(result["adapterId"])

    def test_queued_cancel_never_spawns_and_releases_lease(self):
        lora_jobs.cancel_job(self.identifier)
        with patch.object(lora_jobs, "release_training") as release, patch.object(lora_jobs.subprocess, "Popen") as spawn:
            lora_jobs._run(self.identifier, {"enginePath": "/unused"})
        spawn.assert_not_called()
        release.assert_called_once_with(self.identifier)
        self.assertEqual(lora_jobs.get_job(self.identifier)["status"], "cancelled")

    def test_completed_progress_without_successful_process_does_not_import(self):
        process = MagicMock()
        process.stdout = iter(['SCENA_PROGRESS ' + json.dumps({"step": 3}) + "\n"])
        process.wait.return_value = 1
        process.poll.return_value = 1
        with patch.object(lora_jobs.subprocess, "Popen", return_value=process), patch.object(lora_jobs, "import_adapter") as publish, patch.object(lora_jobs, "release_training"):
            lora_jobs._run(self.identifier, {"enginePath": "/tmp", "pythonPath": "fake"})
        publish.assert_not_called()
        self.assertEqual(lora_jobs.get_job(self.identifier)["status"], "failed")

    def test_success_only_publishes_validated_final_adapter(self):
        process = MagicMock()
        process.stdout = iter(['SCENA_PROGRESS ' + json.dumps({"step": 3}) + "\n"])
        process.wait.return_value = 0
        process.poll.return_value = 0
        with patch.object(lora_jobs.subprocess, "Popen", return_value=process), patch.object(lora_jobs, "import_adapter", return_value={"id": "asset"}) as publish, patch.object(lora_jobs, "release_training"):
            lora_jobs._run(self.identifier, {"enginePath": "/tmp", "pythonPath": "fake"})
        self.assertTrue(publish.call_args.args[0].endswith("training/checkpoint_final"))
        self.assertEqual(lora_jobs.get_job(self.identifier)["adapterId"], "asset")

    def test_settings_reject_nonfinite_unknown_and_partial_numeric_drafts(self):
        for settings in ({"learningRate": float("nan")}, {"batchSize": 1.5}, {"maxSteps": "-"}, {"other": 1}):
            with self.assertRaises(HTTPException):
                lora_jobs._settings("check", settings)

    def test_unreviewed_trainer_source_is_rejected(self):
        with self.assertRaises(ValueError):
            compatible_trainer(b"print('unknown')")

    def test_consume_failure_terminates_owned_child_before_releasing_reservation(self):
        process = MagicMock()
        process.poll.return_value = None
        order = []
        with patch.object(lora_jobs.subprocess, "Popen", return_value=process), \
             patch.object(lora_jobs, "_consume", side_effect=OSError("log write failed")), \
             patch.object(lora_jobs, "_terminate", side_effect=lambda owned: order.append(("terminate", owned))), \
             patch.object(lora_jobs, "release_training", side_effect=lambda _: order.append(("release", None))):
            lora_jobs._run(self.identifier, {"enginePath": "/tmp", "pythonPath": "fake"})
        self.assertEqual(order, [("terminate", process), ("release", None)])
        self.assertEqual(lora_jobs.get_job(self.identifier)["status"], "failed")

    def test_cancel_signal_targets_only_owned_process_group_and_reaps(self):
        process = MagicMock()
        process.poll.return_value = None
        process.pid = 123456
        with patch.object(lora_jobs.os, "killpg") as kill:
            lora_jobs._terminate(process)
        kill.assert_called_once_with(process.pid, lora_jobs.signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=5)

    def test_natural_exit_during_sigkill_is_reaped_and_reservation_released(self):
        process = MagicMock()
        process.pid = 123456
        process.poll.return_value = None
        process.wait.side_effect = [lora_jobs.subprocess.TimeoutExpired("owned", 5), 0]
        with patch.object(lora_jobs.subprocess, "Popen", return_value=process), \
             patch.object(lora_jobs, "_consume", side_effect=OSError("log write failed")), \
             patch.object(lora_jobs.os, "killpg", side_effect=[None, ProcessLookupError()]) as kill, \
             patch.object(lora_jobs, "release_training") as release:
            lora_jobs._run(self.identifier, {"enginePath": "/tmp", "pythonPath": "fake"})
        self.assertEqual([call.args[1] for call in kill.call_args_list],
                         [lora_jobs.signal.SIGTERM, lora_jobs.signal.SIGKILL])
        self.assertEqual(process.wait.call_count, 2)
        release.assert_called_once_with(self.identifier)
        self.assertNotIn(self.identifier, lora_jobs._PROCESSES)

    def test_cancelling_twice_does_not_spawn_another_termination_thread(self):
        process = MagicMock()
        with patch.dict(lora_jobs._PROCESSES, {self.identifier: process}), \
             patch.object(lora_jobs.threading, "Thread") as thread:
            self.assertEqual(lora_jobs.cancel_job(self.identifier)["status"], "cancelling")
            self.assertEqual(lora_jobs.cancel_job(self.identifier)["status"], "cancelling")
        self.assertEqual(thread.call_count, 1)

    def test_sigterm_natural_exit_is_still_reaped(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(lora_jobs.os, "killpg", side_effect=ProcessLookupError()):
            lora_jobs._terminate(process)
        process.wait.assert_called_once_with(timeout=5)

    def test_check_and_normal_modes_default_to_input_duration_not_two_second_cap(self):
        for mode in ("check", "normal"):
            self.assertIsNone(lora_jobs._settings(mode, {})["maxSeconds"])
            self.assertIsNone(lora_jobs._settings(mode, {"maxSeconds": None})["maxSeconds"])
            self.assertEqual(lora_jobs._settings(mode, {"maxSeconds": 10})["maxSeconds"], 10)
        self.assertEqual(lora_jobs._settings("check", {})["maxSteps"], 3)
        self.assertEqual(lora_jobs._settings("normal", {})["maxSteps"], 1000)

    def test_continuation_is_frozen_before_job_launch_and_invalid_source_never_spawns(self):
        request = {"datasetId": "fixture", "name": "continued", "sourceAdapterId": "source", "mode": "check", "rows": []}
        runtime = {"checkpoint": "base"}
        for invalid in (False, True):
            with patch.object(lora_jobs, "reserve_training"), patch.object(lora_jobs, "release_training") as release, \
                 patch.object(lora_jobs, "training_runtime", return_value=runtime), \
                 patch.object(lora_jobs, "freeze_rows", return_value=[{"durationSeconds": 3}]), \
                 patch.object(lora_jobs, "freeze_adapter", side_effect=HTTPException(422, "invalid") if invalid else None,
                              return_value={"assetId": "source", "configHash": "config", "weightsHash": "weights"}) as freeze, \
                 patch.object(lora_jobs.threading, "Thread") as thread:
                if invalid:
                    with self.assertRaises(HTTPException):
                        lora_jobs.start_job(request)
                    thread.assert_not_called()
                    release.assert_called_once()
                else:
                    job = lora_jobs.start_job(request)
                    captured = json.loads((owned_path("jobs", job["id"]) / "request.json").read_text())
                    self.assertEqual(captured["sourceAdapter"]["assetId"], "source")
                    self.assertEqual(job["sourceAdapterId"], "source")
                    thread.return_value.start.assert_called_once()
                freeze.assert_called_once()

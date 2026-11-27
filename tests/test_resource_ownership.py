from __future__ import annotations

import scena_test_isolation  # noqa: F401
import subprocess
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from server import app as _app  # noqa: F401
from server.modules import inference, local_llm_runtime, resource_coordinator as resources, runtime_state, windows_external_memory


class ResourceOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {"MEMORY_OWNER": "tts", "MEMORY_REASON": "test", "LLM_RESIDENT": False,
                            "_OPERATION_GENERATION": 1, "_OWNER_GENERATIONS": {"tts": 1, "llm": 0}}.items():
            self.stack.enter_context(patch.object(resources, name, value))
        self.stack.enter_context(patch.object(runtime_state, "INFERENCE_WORKER", None))
        self.stack.enter_context(patch.object(inference, "INFERENCE_WORKER_FAILED", False))
        self.stack.enter_context(patch.object(inference, "INFERENCE_METAL_BYTES", 100))
        self.stack.enter_context(patch.object(resources, "_can_retain_tts_for_builtin_llm", return_value=False))
        self.stack.enter_context(patch.object(resources, "_windows_exclusive", return_value=False))
        self.stack.enter_context(patch("server.modules.tts_runtime.mark_tts_released"))

    def assert_resource_lock_available(self):
        result = []

        def inspect():
            acquired = resources.RESOURCE_LOCK.acquire(timeout=0.2)
            result.append(acquired)
            if acquired:
                resources.RESOURCE_LOCK.release()

        thread = threading.Thread(target=inspect, daemon=True)
        thread.start()
        thread.join(1)
        self.assertEqual(result, [True], "process work must run outside RESOURCE_LOCK")

    def test_llm_acquire_and_worker_stop_cross_in_either_order(self):
        for first_is_llm in (False, True):
            with self.subTest(first_is_llm=first_is_llm):
                barrier = threading.Barrier(2)
                errors = []
                worker = Mock()
                worker.poll.return_value = None
                worker.terminate.side_effect = self.assert_resource_lock_available
                runtime_state.INFERENCE_WORKER = worker

                def run(action):
                    try:
                        barrier.wait(timeout=1)
                        action()
                    except BaseException as error:
                        errors.append(error)

                actions = [lambda: resources.acquire_llm_memory("load"), inference.shutdown_inference_worker]
                if not first_is_llm:
                    actions.reverse()
                threads = [threading.Thread(target=run, args=(action,), daemon=True) for action in actions]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(2)
                self.assertFalse(any(thread.is_alive() for thread in threads))
                self.assertEqual(errors, [])
                self.assertEqual(resources.MEMORY_OWNER, "llm")
                self.assertIsNone(runtime_state.INFERENCE_WORKER)
                worker.terminate.assert_called_once()

    def test_retain_policy_does_not_unconditionally_stop_tts(self):
        worker = Mock()
        worker.poll.return_value = None
        runtime_state.INFERENCE_WORKER = worker
        with patch.object(resources, "_can_retain_tts_for_builtin_llm", return_value=True):
            resources.acquire_llm_memory("coexist")
        worker.terminate.assert_not_called()
        self.assertTrue(resources.memory_ownership()["ttsResident"])

    def test_windows_llm_always_stops_tts_while_darwin_keeps_existing_policy(self):
        with patch.object(resources, "_can_retain_tts_for_builtin_llm", return_value=True), patch.object(
            inference, "shutdown_inference_worker",
        ) as stop:
            with patch.object(resources, "_windows_exclusive", return_value=False):
                resources.acquire_llm_memory("mac")
            stop.assert_not_called()
            with patch.object(resources, "_windows_exclusive", return_value=True):
                resources.acquire_llm_memory("windows")
            stop.assert_called_once()

    def test_tts_holds_runtime_serialization_only_on_windows(self):
        with patch.object(inference.sys, "platform", "darwin"):
            self.assertIsNot(inference._runtime_serialization(), inference.RUNTIME_SERIALIZATION)
        with patch.object(inference.sys, "platform", "win32"):
            self.assertIs(inference._runtime_serialization(), inference.RUNTIME_SERIALIZATION)

    def test_stale_release_does_not_clear_a_new_acquisition(self):
        previous = resources.memory_generation("tts")
        with patch.object(local_llm_runtime, "unload_local_llm"):
            resources.acquire_tts_memory("new")
        resources.release_memory("tts", generation=previous)
        self.assertEqual(resources.MEMORY_OWNER, "tts")
        self.assertEqual(resources.MEMORY_REASON, "new")

    def test_stop_handles_absent_exited_and_killed_workers(self):
        for state in ("absent", "exited", "kill"):
            with self.subTest(state=state):
                worker = None if state == "absent" else Mock()
                if worker is not None:
                    worker.poll.return_value = 0 if state == "exited" else None
                    worker.wait.side_effect = [subprocess.TimeoutExpired("worker", 3), subprocess.TimeoutExpired("worker", 5), 0]
                runtime_state.INFERENCE_WORKER = worker
                resources.MEMORY_OWNER = "tts"
                inference.shutdown_inference_worker()
                self.assertIsNone(runtime_state.INFERENCE_WORKER)
                self.assertIsNone(resources.MEMORY_OWNER)
                if state == "kill":
                    worker.kill.assert_called_once()
                    self.assertEqual(worker.wait.call_count, 3)

    def test_failed_stop_preserves_process_and_prevents_reuse(self):
        worker = Mock()
        worker.poll.return_value = None
        worker.terminate.side_effect = OSError("stop failed")
        runtime_state.INFERENCE_WORKER = worker
        with self.assertRaisesRegex(OSError, "stop failed"):
            resources.acquire_llm_memory("load")
        self.assertIs(runtime_state.INFERENCE_WORKER, worker)
        self.assertEqual(resources.MEMORY_OWNER, "tts")
        with self.assertRaisesRegex(OSError, "stop failed"):
            inference.inference_worker_locked(None)

    def test_runtime_stop_and_tts_acquisition_do_not_hold_resource_lock(self):
        process = Mock()
        process.poll.return_value = None
        process.terminate.side_effect = self.assert_resource_lock_available
        with patch.object(local_llm_runtime, "RUNTIME_PROCESS", process), patch.object(
            local_llm_runtime, "local_llm_status", return_value={},
        ), patch.dict("os.environ", {}, clear=True):
            resources.acquire_tts_memory("generate")
            self.assertIsNone(local_llm_runtime.RUNTIME_PROCESS)
        self.assertEqual(resources.MEMORY_OWNER, "tts")

    def test_coexistence_prepare_does_not_release_any_llm(self):
        with patch.object(windows_external_memory, "release_windows_external_llm") as release_external, patch.object(
            local_llm_runtime, "unload_local_llm",
        ) as unload_local:
            resources.acquire_tts_memory("prewarm", coexist=True)
        release_external.assert_not_called()
        unload_local.assert_not_called()

    def test_runtime_stop_failure_keeps_model_ownership(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired("runtime", 5)
        resources.MEMORY_OWNER, resources.LLM_RESIDENT = "llm", True
        with patch.object(local_llm_runtime, "RUNTIME_PROCESS", process), self.assertRaises(subprocess.TimeoutExpired):
            local_llm_runtime.stop_local_llm()
        self.assertEqual(resources.MEMORY_OWNER, "llm")
        self.assertTrue(resources.LLM_RESIDENT)

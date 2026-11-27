"""Background model loading yields the CPU; a generation takes it back at once (Windows)."""
from __future__ import annotations

import scena_test_isolation  # noqa: F401
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import server.app  # noqa: F401
from server.modules import inference, worker_priority

BELOW_NORMAL, NORMAL = 0x4000, 0x20


class WorkerPriorityTests(unittest.TestCase):
    def _worker(self):
        worker = MagicMock(pid=4321)
        worker.poll.return_value = None
        return worker

    def test_windows_worker_switches_between_background_and_normal_priority(self):
        process = MagicMock()
        with patch.object(worker_priority.sys, "platform", "win32"), \
                patch.object(worker_priority.psutil, "Process", return_value=process) as factory:
            worker_priority.set_worker_background(self._worker(), True)
            worker_priority.set_worker_background(self._worker(), False)
        factory.assert_called_with(4321)
        self.assertEqual([call.args[0] for call in process.nice.call_args_list], [BELOW_NORMAL, NORMAL])

    def test_other_platforms_and_stopped_workers_are_left_alone(self):
        stopped = self._worker()
        stopped.poll.return_value = 0
        with patch.object(worker_priority.psutil, "Process") as factory:
            with patch.object(worker_priority.sys, "platform", "darwin"):
                worker_priority.set_worker_background(self._worker(), True)
            with patch.object(worker_priority.sys, "platform", "win32"):
                worker_priority.set_worker_background(stopped, True)
                worker_priority.set_worker_background(None, True)
        factory.assert_not_called()

    def test_preparation_loads_the_worker_at_background_priority(self):
        worker = self._worker()
        with patch("server.modules.resource_coordinator.acquire_tts_memory"), \
                patch.object(inference, "engine_dir", return_value=Path(".")), \
                patch.object(inference, "inference_worker_locked", return_value=worker), \
                patch.object(inference, "_exchange_response", return_value={}), \
                patch("server.modules.tts_registry.selected_model_capabilities", return_value={}), \
                patch("server.modules.worker_priority.set_worker_background") as priority:
            inference.prepare_irodori_worker()
        priority.assert_called_once_with(worker, True)

    def test_generation_restores_priority_before_waiting_for_a_running_load(self):
        worker = self._worker()
        held, release, raised = threading.Event(), threading.Event(), threading.Event()

        def load_model():
            with inference.RUNTIME_SERIALIZATION:
                held.set()
                release.wait(10)

        loader = threading.Thread(target=load_model, daemon=True)
        loader.start()
        self.assertTrue(held.wait(5))
        with patch.object(inference.sys, "platform", "win32"), \
                patch("server.modules.runtime_state.INFERENCE_WORKER", worker), \
                patch.object(inference, "_run_with_memory", return_value=[]), \
                patch("server.modules.worker_priority.set_worker_background",
                             side_effect=lambda *_: raised.set()) as priority:
            generation = threading.Thread(target=lambda: inference.run_irodori(
                text="a", caption=None, output=Path(tempfile.gettempdir()) / "scena-priority-test.wav", seed=0, ref_wav=None, quality="fast"), daemon=True)
            generation.start()
            self.assertTrue(raised.wait(2), "priority was restored only after the load finished")
            release.set()
            generation.join(5)
        loader.join(5)
        priority.assert_called_with(worker, False)


    def test_a_generation_runs_at_normal_priority_even_on_a_worker_started_by_a_load(self):
        worker = self._worker()
        calls = []
        with patch.object(inference, "engine_dir", return_value=Path(".")), \
                patch.object(inference, "synthesis_request", return_value={"operation": "generate"}), \
                patch("server.modules.tts_registry.selected_model_capabilities", return_value={}), \
                patch.object(inference, "inference_worker_locked", side_effect=lambda _engine: calls.append("worker") or worker), \
                patch.object(inference, "_exchange_response", side_effect=lambda *_: calls.append("exchange") or {}), \
                patch("server.modules.worker_priority.set_worker_background",
                      side_effect=lambda w, background: calls.append(("priority", w, background))):
            with self.assertRaises(Exception):
                inference._run_irodori(text="a", caption=None, output=Path(tempfile.gettempdir()) / "scena-priority.wav",
                                       seed=0, ref_wav=None, quality="fast")
        self.assertEqual(calls[:3], ["worker", ("priority", worker, False), "exchange"])


if __name__ == "__main__":
    unittest.main()

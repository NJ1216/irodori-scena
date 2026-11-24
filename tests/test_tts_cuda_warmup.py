from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import inference, tts_cuda_warmup as warmup


class _Worker:
    def poll(self):
        return None


class CudaWarmupRequestTests(unittest.TestCase):
    def test_requests_cover_each_quality_with_and_without_reference_and_caption(self) -> None:
        requests = warmup.warmup_requests({})
        self.assertEqual(len(requests), 12)
        routes = {(item["steps"], item["schedule"], item["referenceProbe"], bool(item["caption"])) for item in requests}
        for quality in ("turbo", "fast", "quality"):
            generation = inference.synthesis_request(
                text="x", caption=None, output=None, seed=0, ref_wav=None, quality=quality,
                generation_settings=None, num_candidates=1, lora_adapter=None, capabilities={})
            for reference in (False, True):
                for caption in (False, True):
                    self.assertIn((generation["steps"], generation["schedule"], reference, caption), routes)
        for item in requests:
            self.assertEqual((item["operation"], item["numCandidates"], item["output"], item["refWav"], item["loraAdapter"]),
                             ("calibrate", 1, None, None, None))

    def test_meanflow_models_need_no_calibration(self) -> None:
        self.assertEqual(warmup.warmup_requests({"flowParameterization": "meanflow"}), [])


class CudaWarmupLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sent = []
        self.patches = [
            patch.object(warmup.sys, "platform", "win32"),
            patch("server.modules.tts_registry.selected_model_capabilities", lambda: {}),
            patch("server.modules.runtime_state.INFERENCE_WORKER", _Worker()),
            patch.object(inference, "exchange_worker_request", lambda _worker, request: self.sent.append(request) or {"ok": True}),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()

    def test_every_route_is_sent_once(self) -> None:
        self.assertEqual(warmup.calibrate_common_routes(lambda: True), {"state": "complete", "calibrated": 12})
        self.assertEqual(len(self.sent), 12)

    def test_stops_before_the_next_route_when_asked(self) -> None:
        answers = iter([True, False])
        self.assertEqual(warmup.calibrate_common_routes(lambda: next(answers))["state"], "paused")
        self.assertEqual(len(self.sent), 1)

    def test_a_waiting_generation_stops_the_loop(self) -> None:
        lock = threading.Lock()
        lock.acquire()
        answers = iter([True, False])
        with patch.object(inference, "INFERENCE_SYNTHESIS_LOCK", lock):
            self.assertEqual(warmup.calibrate_common_routes(lambda: next(answers))["state"], "paused")
        self.assertEqual(self.sent, [])

    def test_waits_for_a_finishing_generation_then_continues(self) -> None:
        lock = threading.Lock()
        lock.acquire()
        with patch.object(inference, "INFERENCE_SYNTHESIS_LOCK", lock), patch.object(warmup.time, "sleep", lambda _s: lock.release() if lock.locked() else None):
            self.assertEqual(warmup.calibrate_common_routes(lambda: True)["state"], "complete")
        self.assertEqual(len(self.sent), 12)

    def test_a_failed_route_releases_the_stopped_worker_and_marks_the_runtime_stopped(self) -> None:
        calls = []

        def failing(_worker, _request):
            raise RuntimeError("worker stopped")

        with patch.object(inference, "exchange_worker_request", failing), patch(
            "server.modules.resource_coordinator.release_memory", lambda owner: calls.append(("release", owner)),
        ), patch("server.modules.tts_runtime.reset_tts_runtime", lambda reason=None: calls.append(("reset", reason))):
            warmup.calibrate_common_routes(lambda: True)
        self.assertEqual(calls, [("release", "tts"), ("reset", "calibration-worker-error")])

    def test_a_slow_route_stops_background_calibration(self) -> None:
        clock = iter([0.0, warmup.ROUTE_BUDGET_SECONDS + 1])
        with patch.object(warmup.time, "monotonic", lambda: next(clock)):
            result = warmup.calibrate_common_routes(lambda: True)
        self.assertEqual((result["state"], result["reason"], len(self.sent)), ("stopped", "slow-route", 1))

    def test_never_starts_a_worker(self) -> None:
        with patch("server.modules.runtime_state.INFERENCE_WORKER", None):
            self.assertEqual(warmup.calibrate_common_routes(lambda: True)["reason"], "no-worker")
        self.assertEqual(self.sent, [])

    def test_a_worker_error_stops_the_loop_without_raising(self) -> None:
        def failing(_worker, _request):
            raise RuntimeError("worker stopped")

        with patch.object(inference, "exchange_worker_request", failing), patch(
            "server.modules.resource_coordinator.release_memory", lambda _owner: None,
        ), patch("server.modules.tts_runtime.reset_tts_runtime", lambda reason=None: None):
            result = warmup.calibrate_common_routes(lambda: True)
        self.assertEqual((result["state"], result["reason"]), ("stopped", "worker-error"))

    def test_other_platforms_do_nothing(self) -> None:
        with patch.object(warmup.sys, "platform", "darwin"):
            self.assertEqual(warmup.calibrate_common_routes(lambda: True)["state"], "skipped")
        self.assertEqual(self.sent, [])

    def test_only_one_background_run_at_a_time_and_completed_models_are_not_rerun(self) -> None:
        started = []
        with patch.object(warmup.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: started.append(kw))):
            self.assertTrue(warmup.start_cuda_calibration("model-a", lambda: True))
            self.assertFalse(warmup.start_cuda_calibration("model-a", lambda: True))
            started[0]["target"](*started[0]["args"])
            self.assertFalse(warmup.start_cuda_calibration("model-a", lambda: True))
            self.assertTrue(warmup.start_cuda_calibration("model-b", lambda: True))
            with patch.object(warmup, "calibrate_common_routes", lambda _c: {"state": "paused"}):
                started[1]["target"](*started[1]["args"])
            self.assertTrue(warmup.start_cuda_calibration("model-b", lambda: True), "a paused run resumes later")
            with patch.object(warmup, "calibrate_common_routes", lambda _c: {"state": "stopped", "reason": "slow-route"}):
                started[2]["target"](*started[2]["args"])
            self.assertFalse(warmup.start_cuda_calibration("model-b", lambda: True), "a stopped run is not retried this session")
        warmup._COMPLETED.clear()
        if warmup._RUNNING.locked():
            warmup._RUNNING.release()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import contextlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import irodori_acceleration_adapter as adapter
from server.irodori_acceleration_adapter import CALIBRATE_PROFILE, CUDA_PROFILE, EAGER_PROFILE, run, select_profile
from server.irodori_cuda_calibration import CalibrationStore, same_audio

ENGINE = "8224dafb46d0aba89209a8f905f1cb7e3299d9c1"
FP32 = "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
QUANTIZED = "Aratako/Irodori-TTS-v4.1-Small-Quantized@ef04e6c3ba56138ae23e86a2eabc004f76990e37"
GPU = ("NVIDIA GeForce RTX 3060", "2.10.0+cu128", "12.8")
ROUTE = SimpleNamespace(t_schedule_mode="sway", num_steps=16, no_ref=True)


class _Model:
    def encode_conditions(self, **_kwargs):
        return ()

    def forward_with_encoded_conditions(self, **_kwargs):
        return None

    def build_context_kv_cache(self, **_kwargs):
        return []


class _CudaRuntime:
    model_device = "cuda:0"
    model = _Model()
    key = SimpleNamespace(codec_deterministic_encode=True)

    def __init__(self, optimized_audio=(1, 2, 3), optimized_error=None):
        self.optimized = False
        self.optimized_audio = list(optimized_audio)
        self.optimized_error = optimized_error
        self.calls = []

    def _load_reference_latent(self, **_kwargs):
        return None, None

    def synthesize(self, req, *, log_fn=None):
        del req, log_fn
        self.calls.append("optimized" if self.optimized else "eager")
        if self.optimized and self.optimized_error:
            raise self.optimized_error
        audio = self.optimized_audio if self.optimized else [1, 2, 3]
        return SimpleNamespace(audio=audio, sample_rate=48000, stage_timings=[("sample_rf", 0.01)])


@contextlib.contextmanager
def _optimized(runtime, _request, _engine, _stats, _graphs=False):
    runtime.optimized = True
    try:
        yield SimpleNamespace(clear=lambda: None)
    finally:
        runtime.optimized = False


class CalibrationStoreTests(unittest.TestCase):
    def test_records_survive_reload_and_corrupt_files_start_empty(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "tts" / "calibration.json"
            store = CalibrationStore(path)
            self.assertIsNone(store.status("key"))
            store.record("key", "promoted", eager_seconds=1.0, adapter_seconds=0.8)
            self.assertEqual(CalibrationStore(path).status("key"), "promoted")
            path.write_text("{broken", encoding="utf-8")
            self.assertIsNone(CalibrationStore(path).status("key"))
            CalibrationStore(path).record("other", "rejected")
            self.assertEqual(CalibrationStore(path).status("other"), "rejected")

    def test_an_unreadable_file_is_not_overwritten_with_fewer_routes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "calibration.json"
            CalibrationStore(path).record("kept", "promoted")
            with patch.object(Path, "read_text", side_effect=PermissionError("locked")):
                with self.assertRaises(OSError):
                    CalibrationStore(path).record("new", "promoted")
                self.assertIsNone(CalibrationStore(path).status("kept"))
            self.assertEqual(CalibrationStore(path).status("kept"), "promoted")

    def test_every_candidate_must_match(self) -> None:
        first = SimpleNamespace(audio=[1], audios=[[1], [2]], sample_rate=48000)
        second = SimpleNamespace(audio=[1], audios=[[1], [3]], sample_rate=48000)
        self.assertFalse(same_audio(first, second))
        self.assertTrue(same_audio(first, SimpleNamespace(audio=[1], audios=[[1], [2]], sample_rate=48000)))


class CudaCalibrationProfileTests(unittest.TestCase):
    def _decide(self, store, identity=FP32, variant="pytorch-fp32"):
        with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=GPU):
            return select_profile(_CudaRuntime(), ENGINE, identity, ROUTE, variant_id=variant, calibration=store)

    def test_unverified_gpu_routes_calibrate_then_follow_the_recorded_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            for identity, variant in [(FP32, "pytorch-fp32"), (QUANTIZED, "pytorch-w8a16"), (QUANTIZED, "pytorch-w4a16")]:
                with self.subTest(variant=variant):
                    self.assertEqual(self._decide(store, identity, variant).profile, CALIBRATE_PROFILE)
            key = self._decide(store).calibration_key
            store.record(key, "promoted")
            self.assertEqual(self._decide(store).profile, CUDA_PROFILE)
            store.record(key, "rejected")
            decision = self._decide(store)
            self.assertEqual((decision.profile, decision.fallback_reason), (EAGER_PROFILE, "cuda-calibration-rejected"))

    def test_fp8_and_w8a8_never_calibrate(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            for variant in ("pytorch-fp8-weight-only", "pytorch-fp8-dynamic", "pytorch-w8a8"):
                with self.subTest(variant=variant):
                    decision = self._decide(store, QUANTIZED, variant)
                    self.assertEqual((decision.profile, decision.fallback_reason), (EAGER_PROFILE, "cuda-variant-unsupported"))

    def test_caption_use_and_candidate_count_are_calibrated_separately(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            store.record(self._decide(store).calibration_key, "promoted")
            for change in ({"caption": "明るく"}, {"num_candidates": 2}):
                with self.subTest(change=change), patch.dict(ROUTE.__dict__, change):
                    self.assertEqual(self._decide(store).profile, CALIBRATE_PROFILE)

    def test_without_a_store_unverified_routes_stay_eager(self) -> None:
        decision = self._decide(None)
        self.assertEqual((decision.profile, decision.fallback_reason), (EAGER_PROFILE, "cuda-route-not-promoted"))


class CalibrationNeededTests(unittest.TestCase):
    def test_only_unrecorded_cuda_routes_need_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            arguments = dict(engine_commit=ENGINE, model_identity=FP32, variant_id="pytorch-fp32", calibration=store)
            with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=GPU):
                self.assertTrue(adapter.calibration_needed(_CudaRuntime(), ROUTE, **arguments))
                store.record(select_profile(_CudaRuntime(), ENGINE, FP32, ROUTE, calibration=store).calibration_key, "promoted")
                self.assertFalse(adapter.calibration_needed(_CudaRuntime(), ROUTE, **arguments))
                self.assertFalse(adapter.calibration_needed(_CudaRuntime(), ROUTE, **{**arguments, "variant_id": "pytorch-w8a8"}))


class CudaGraphSelectionTests(unittest.TestCase):
    def _run(self, steps, variant, identity=FP32):
        entered = []

        @contextlib.contextmanager
        def recording_graphs(_torch, _model, forward):
            entered.append(steps)
            yield lambda **kw: ("graphed", forward(**kw))

        runtime = _CudaRuntime()
        forwarded = []
        runtime.synthesize = lambda req, *, log_fn=None: forwarded.append(runtime.model.forward_with_encoded_conditions(x_t=1, t=2)) or SimpleNamespace(
            audio=[1], sample_rate=48000, stage_timings=[])
        request = SimpleNamespace(t_schedule_mode="sway", num_steps=steps, no_ref=True)
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=GPU):
                store.record(select_profile(runtime, ENGINE, identity, request, variant_id=variant, calibration=store).calibration_key, "promoted")
                with patch.object(adapter, "step_graphs", recording_graphs), patch.object(adapter, "_normalized", str), patch.dict(sys.modules[__name__].__dict__, {"sample_euler_rf_cfg": None}), patch.dict(sys.modules, {"torch": SimpleNamespace()}):
                    _result, execution = run(runtime, request, engine_commit=ENGINE, model_identity=identity, variant_id=variant, calibration=store)
        return entered, forwarded, execution

    def test_graphs_replay_the_forward_from_16_steps_for_fp32_and_always_for_quantized(self) -> None:
        for steps, variant, identity, expected in [(16, "pytorch-fp32", FP32, True), (8, "pytorch-fp32", FP32, False), (8, "pytorch-w8a16", QUANTIZED, True)]:
            with self.subTest(steps=steps, variant=variant):
                entered, forwarded, execution = self._run(steps, variant, identity)
                self.assertEqual(execution["optimizationProfile"], CUDA_PROFILE, execution["optimizationStats"].get("fallbackDetail"))
                self.assertEqual(bool(entered), expected)
                self.assertEqual(isinstance(forwarded[0], tuple) and forwarded[0][0] == "graphed", expected)
                self.assertEqual(execution["optimizationStats"].get("cudaGraphs", False), expected)

    def test_calibration_records_name_the_profile_so_older_promotions_recalibrate(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=GPU):
                key = select_profile(_CudaRuntime(), ENGINE, FP32, ROUTE, variant_id="pytorch-fp32", calibration=store).calibration_key
        self.assertIn(CUDA_PROFILE, key)


class EagerRetryTests(unittest.TestCase):
    def test_the_eager_retry_runs_after_the_failed_attempt_is_released(self) -> None:
        runtime = _CudaRuntime()
        seen = []

        @contextlib.contextmanager
        def failing(*_args):
            raise RuntimeError("capture failed")
            yield  # pragma: no cover

        original = runtime.synthesize
        runtime.synthesize = lambda req, *, log_fn=None: seen.append(sys.exc_info()[0]) or original(req, log_fn=log_fn)
        with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=GPU), patch.object(adapter, "_optimized_calls", failing):
            store = CalibrationStore(Path(tempfile.mkdtemp()) / "c.json")
            store.record(select_profile(runtime, ENGINE, FP32, ROUTE, calibration=store).calibration_key, "promoted")
            _result, execution = run(runtime, ROUTE, engine_commit=ENGINE, model_identity=FP32, calibration=store)
        self.assertEqual(execution["fallbackReason"], "optimized-path-failed")
        self.assertEqual(seen, [None])


class CudaCalibrationRunTests(unittest.TestCase):
    def _run(self, runtime, store):
        with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=GPU), patch.object(
            adapter, "_optimized_calls", _optimized
        ):
            return run(runtime, ROUTE, engine_commit=ENGINE, model_identity=FP32, variant_id="pytorch-fp32", calibration=store)

    def test_identical_output_promotes_and_returns_the_eager_result(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            runtime = _CudaRuntime()
            result, execution = self._run(runtime, store)
            self.assertEqual(runtime.calls, ["eager", "optimized"])
            self.assertEqual(result.audio, [1, 2, 3])
            self.assertEqual((execution["optimizationProfile"], execution["fallbackReason"]), (EAGER_PROFILE, "cuda-calibration-promoted"))
            runtime.calls.clear()
            _result, execution = self._run(runtime, store)
            self.assertEqual(runtime.calls, ["optimized"])
            self.assertEqual(execution["optimizationProfile"], CUDA_PROFILE)

    def test_out_of_memory_leaves_the_route_uncalibrated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            runtime = _CudaRuntime(optimized_error=RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"))
            result, execution = self._run(runtime, store)
            self.assertEqual((result.audio, execution["fallbackReason"]), ([1, 2, 3], "cuda-calibration-deferred"))
            runtime.calls.clear()
            self._run(runtime, store)
            self.assertEqual(runtime.calls, ["eager", "optimized"])

    def test_a_failed_save_still_returns_the_generated_audio(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = CalibrationStore(Path(root) / "calibration.json")
            with patch.object(CalibrationStore, "record", side_effect=PermissionError("locked")):
                result, execution = self._run(_CudaRuntime(), store)
            self.assertEqual((result.audio, execution["fallbackReason"]), ([1, 2, 3], "cuda-calibration-promoted"))

    def test_different_output_or_adapter_failure_rejects_and_keeps_eager(self) -> None:
        for runtime in (_CudaRuntime(optimized_audio=(1, 2, 4)), _CudaRuntime(optimized_error=RuntimeError("dtype mismatch"))):
            with self.subTest(error=runtime.optimized_error), tempfile.TemporaryDirectory() as root:
                store = CalibrationStore(Path(root) / "calibration.json")
                result, execution = self._run(runtime, store)
                self.assertEqual(result.audio, [1, 2, 3])
                self.assertEqual(execution["fallbackReason"], "cuda-calibration-rejected")
                runtime.calls.clear()
                self._run(runtime, store)
                self.assertEqual(runtime.calls, ["eager"])


if __name__ == "__main__":
    unittest.main()

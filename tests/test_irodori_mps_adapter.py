from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server.irodori_acceleration_adapter import (
    CUDA_PROFILE,
    EAGER_PROFILE,
    MEANFLOW_PROFILE,
    PROFILE,
    TensorLru,
    cache_budget,
    cuda_cache_budget,
    clear_worker_caches,
    reference_identity,
    run,
    select_profile,
)
from server.irodori_acceleration_sampler import _context_caches, wait_for_ui_idle


class _Model:
    def encode_conditions(self, **_kwargs):
        return ()

    def forward_with_encoded_conditions(self, **_kwargs):
        return None

    def build_context_kv_cache(self, **_kwargs):
        return []


class _Runtime:
    model_device = "mps"
    model = _Model()
    key = SimpleNamespace(codec_deterministic_encode=True)

    def __init__(self, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.calls = 0

    def _load_reference_latent(self, **_kwargs):
        return None, None

    def synthesize(self, req, *, log_fn=None):
        del req, log_fn
        self.calls += 1
        if self.fail_once and self.calls == 1:
            raise RuntimeError("optimized failure")
        return SimpleNamespace(stage_timings=[("sample_rf", 0.01)])


class MpsAdapterTests(unittest.TestCase):
    def test_meanflow_uses_upstream_sampler_without_rf_patch(self) -> None:
        runtime = _Runtime()
        runtime.model_cfg = SimpleNamespace(flow_parameterization="meanflow")
        decision = select_profile(
            runtime,
            "89f9d8fbd4d51ea019867ee1197725ede1df13c5",
            "Aratako/Irodori-TTS-v4.1-Small-MF@ccc78f5d480b6e51b69b2d5042a14c4da04fea6e",
            SimpleNamespace(num_steps=4, no_ref=True),
        )
        self.assertEqual(decision.profile, MEANFLOW_PROFILE)
        with patch("server.irodori_acceleration_adapter._optimized_calls", side_effect=AssertionError("RF patch used")):
            _result, execution = run(
                runtime,
                SimpleNamespace(num_steps=4, no_ref=True),
                engine_commit="89f9d8fbd4d51ea019867ee1197725ede1df13c5",
                model_identity="Aratako/Irodori-TTS-v4.1-Small-MF@ccc78f5d480b6e51b69b2d5042a14c4da04fea6e",
            )
        self.assertEqual(execution["optimizationProfile"], MEANFLOW_PROFILE)

    def test_cache_budget_is_quarter_percent_capped_at_128_mib(self) -> None:
        self.assertEqual(cache_budget(None), 0)
        self.assertEqual(cache_budget(16 * 1024**3), 16 * 1024**3 // 400)
        self.assertEqual(cache_budget(128 * 1024**3), 128 * 1024**2)

    def test_cuda_cache_budget_uses_free_vram(self) -> None:
        torch = SimpleNamespace(cuda=SimpleNamespace(mem_get_info=lambda _device: (2 * 1024**3, 8 * 1024**3)))
        self.assertEqual(cuda_cache_budget(torch, "cuda"), 128 * 1024**2)
        torch.cuda.mem_get_info = lambda _device: (800 * 1024**2, 8 * 1024**3)
        self.assertEqual(cuda_cache_budget(torch, "cuda:0"), 50 * 1024**2)

    def test_cuda_never_runs_the_mps_ui_wait(self) -> None:
        torch = SimpleNamespace(mps=SimpleNamespace(synchronize=lambda: self.fail("MPS sync on CUDA")))
        with patch("server.irodori_acceleration_sampler._UI_ACTIVITY_UNTIL", 10**20):
            wait_for_ui_idle(torch, "cuda:0")

    def test_ui_idle_deadline_crossing_does_not_abort_generation(self) -> None:
        torch = SimpleNamespace(mps=SimpleNamespace(synchronize=Mock()))
        # The lease may expire between the loop check and computing the sleep.
        # time.sleep rejects a negative duration, turning a click into a 500.
        with (
            patch("server.irodori_acceleration_sampler._UI_ACTIVITY_UNTIL", 1.0),
            patch("server.irodori_acceleration_sampler.time.monotonic", side_effect=[0.9, 0.999999, 1.000001, 1.000002]),
        ):
            wait_for_ui_idle(torch)
        torch.mps.synchronize.assert_called_once()

    def test_ui_activity_extends_wait_and_then_allows_generation_to_continue(self) -> None:
        from server import irodori_acceleration_sampler as sampler

        torch = SimpleNamespace(mps=SimpleNamespace(synchronize=Mock()))
        now = 10.0
        durations = []

        def sleep(seconds):
            nonlocal now
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, 0.016)
            durations.append(seconds)
            now += seconds
            if len(durations) == 1:
                sampler.note_ui_activity()

        with (
            patch.object(sampler, "_UI_ACTIVITY_UNTIL", now + 0.02),
            patch.object(sampler.time, "monotonic", side_effect=lambda: now),
            patch.object(sampler.time, "sleep", side_effect=sleep),
        ):
            wait_for_ui_idle(torch)
            self.assertGreaterEqual(now, 10.266)
        torch.mps.synchronize.assert_called_once()

    def test_cfg_and_non_cfg_steps_receive_separate_reusable_context_caches(self) -> None:
        calls = []
        model = SimpleNamespace(build_context_kv_cache=lambda **values: calls.append(values) or values)
        encoded = ("batched-text", "mask", "batched-speaker", None, "batched-caption", None)
        conditional = ("text", "mask", "speaker", None, "caption", None)
        bundled, condition_only = _context_caches(model, encoded, conditional, True)
        self.assertEqual(bundled["text_state"], "batched-text")
        self.assertEqual(condition_only["text_state"], "text")
        self.assertEqual(len(calls), 2)

    def test_lru_evicts_oldest_value(self) -> None:
        cache = TensorLru(10)
        cache.put(("a",), "a", 6)
        cache.put(("b",), "b", 6)
        self.assertIsNone(cache.get(("a",)))
        self.assertEqual(cache.get(("b",)), "b")

    def test_reference_identity_changes_after_file_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "voice.wav"
            path.write_bytes(b"one")
            before = reference_identity(str(path))
            path.write_bytes(b"updated")
            after = reference_identity(str(path))
            self.assertNotEqual(before, after)

    def test_profile_requires_verified_engine_and_api_shape(self) -> None:
        runtime = _Runtime()
        accepted_models = (
            "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b",
            "Aratako/Irodori-TTS-v4-Small@4c92c7ee2bb15c19a97cf4e86d24fd6bf33b0135",
        )
        below_threshold_models = (
            "Aratako/Irodori-TTS-600M-v3-VoiceDesign@e863a3a93e652e09afeff3e84823a206a0a60314",
            "Aratako/Irodori-TTS-500M-v3@236c1e56591279fc24e3c1bf6609fc06e48dde28",
            "Aratako/Irodori-TTS-500M-v2@8fd631cafb911dde466bc30dd558a0dc55e8ccae",
        )
        self.assertEqual(select_profile(runtime, "unknown", accepted_models[0]).profile, EAGER_PROFILE)
        for model in accepted_models:
            with self.subTest(model=model):
                self.assertEqual(
                    select_profile(runtime, "8224dafb46d0aba89209a8f905f1cb7e3299d9c1", model).profile,
                    PROFILE,
                )
        for model in below_threshold_models:
            with self.subTest(model=model):
                self.assertEqual(
                    select_profile(runtime, "8224dafb46d0aba89209a8f905f1cb7e3299d9c1", model).profile,
                    EAGER_PROFILE,
                )
        self.assertEqual(
            select_profile(runtime, "8224dafb46d0aba89209a8f905f1cb7e3299d9c1", "unknown").fallback_reason,
            "unverified-model",
        )

    def test_cuda_selects_its_profile_and_cpu_stays_eager(self) -> None:
        runtime = _Runtime()
        runtime.model_device = "cuda:0"
        identity = "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
        route = SimpleNamespace(t_schedule_mode="sway", num_steps=16, no_ref=True)
        verified = {(identity, "RTX", "2.10.0+cu128", "12.8", "sway", 16, False)}
        with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=("RTX", "2.10.0+cu128", "12.8")), patch(
            "server.irodori_acceleration_adapter.VERIFIED_CUDA_ROUTES", verified,
        ):
            decision = select_profile(
                runtime, "8224dafb46d0aba89209a8f905f1cb7e3299d9c1", identity, route,
            )
        self.assertEqual(decision.profile, CUDA_PROFILE)
        runtime.model_device = "cpu"
        self.assertEqual(select_profile(
            runtime,
            "8224dafb46d0aba89209a8f905f1cb7e3299d9c1",
            "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b",
        ).fallback_reason, "unsupported-device")

    def test_unpromoted_cuda_model_stays_eager(self) -> None:
        runtime = _Runtime()
        runtime.model_device = "cuda"
        with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=("RTX", "2.10.0+cu128", "12.8")):
            decision = select_profile(
                runtime,
                "8224dafb46d0aba89209a8f905f1cb7e3299d9c1",
                "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b",
            )
        self.assertEqual(decision.profile, EAGER_PROFILE)
        self.assertEqual(decision.fallback_reason, "cuda-route-not-promoted")

    def test_all_promoted_cuda_routes_are_independent(self) -> None:
        runtime = _Runtime()
        runtime.model_device = "cuda:0"
        identity = "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
        cuda_identity = ("NVIDIA GeForce RTX 4070 Ti", "2.10.0+cu128", "12.8")
        with patch("server.irodori_acceleration_adapter._cuda_runtime_identity", return_value=cuda_identity):
            for schedule, steps in (("sway", 8), ("sway", 16), ("linear", 40)):
                for no_ref in (False, True):
                    with self.subTest(schedule=schedule, steps=steps, no_ref=no_ref):
                        request = SimpleNamespace(t_schedule_mode=schedule, num_steps=steps, no_ref=no_ref)
                        decision = select_profile(
                            runtime, "8224dafb46d0aba89209a8f905f1cb7e3299d9c1", identity, request,
                        )
                        self.assertEqual(decision.profile, CUDA_PROFILE)

    def test_worker_cache_disposal_removes_runtime_entries(self) -> None:
        from server import irodori_acceleration_adapter as adapter

        cache = TensorLru(10)
        cache.put(("key",), "value", 5)
        with patch.object(adapter, "_CACHES", {1: cache}):
            clear_worker_caches()
            self.assertEqual(adapter._CACHES, {})
            self.assertEqual(cache.bytes, 0)

    def test_v2_voice_design_stays_eager_after_performance_regression(self) -> None:
        decision = select_profile(
            _Runtime(),
            "8224dafb46d0aba89209a8f905f1cb7e3299d9c1",
            "Aratako/Irodori-TTS-500M-v2-VoiceDesign@456e55708e7183f5c7faa1448209d54aa8991451",
        )
        self.assertEqual(decision.profile, EAGER_PROFILE)
        self.assertEqual(decision.fallback_reason, "unverified-model")

    def test_optimized_failure_retries_upstream_once_and_records_execution(self) -> None:
        runtime = _Runtime(fail_once=True)
        with patch("server.irodori_acceleration_adapter._optimized_calls", return_value=__import__("contextlib").nullcontext(TensorLru(0))):
            _result, execution = run(
                runtime,
                SimpleNamespace(lora_adapter=None),
                engine_commit="8224dafb46d0aba89209a8f905f1cb7e3299d9c1",
                model_identity="Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b",
            )
        self.assertEqual(runtime.calls, 2)
        self.assertEqual(execution["optimizationProfile"], EAGER_PROFILE)
        self.assertEqual(execution["fallbackReason"], "optimized-path-failed")


if __name__ == "__main__":
    unittest.main()

import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server import mlx_acceleration_adapter as adapter

RUNTIME = "mlx-audio@0.5.0"


class FakeInner:
    def encode_conditions_full(self, **kwargs):
        return ("text", "mask")

    def build_kv_cache(self, *args):
        return ("kv",)

    def forward_with_conditions(self, **kwargs):
        return "velocity"


class FakeCodec:
    def decode(self, latent, chunk_size=50):
        return latent


class FakeModel:
    def __init__(self):
        self.model = FakeInner()
        self.dacvae = FakeCodec()
        self.generate_calls = 0

    def _encode_ref_audios(self, audios, max_ref_seconds=None):
        return ("latent", "mask")

    def generate(self, **kwargs):
        self.generate_calls += 1
        yield SimpleNamespace(audio=[0.0], sample_rate=48000)


def generate_kwargs():
    return {"text": "テスト", "rng_seed": 1}


class SelectProfileTest(unittest.TestCase):
    def test_known_runtime_with_full_api_uses_scena_profile(self):
        decision = adapter.select_profile(FakeModel(), RUNTIME, lora=False)
        self.assertEqual((decision.profile, decision.fallback_reason), (adapter.PROFILE, None))

    def test_missing_method_falls_back_with_api_shape_reason(self):
        model = FakeModel()
        model.model = SimpleNamespace(build_kv_cache=None, forward_with_conditions=None)
        decision = adapter.select_profile(model, RUNTIME, lora=False)
        self.assertEqual((decision.profile, decision.fallback_reason), (adapter.EAGER_PROFILE, "api-shape-mismatch"))

    def test_unknown_runtime_is_not_optimized(self):
        decision = adapter.select_profile(FakeModel(), "mlx-audio@9.9.9", lora=False)
        self.assertEqual(decision.fallback_reason, "unverified-runtime")

    def test_lora_requests_bypass_optimization(self):
        decision = adapter.select_profile(FakeModel(), RUNTIME, lora=True)
        self.assertEqual(decision.fallback_reason, "dynamic-lora")


class DefaultFeaturesTest(unittest.TestCase):
    def test_adopted_features_are_enabled_by_default(self):
        # Adopted 2026-11-23 after measurement: the reuse pair is PCM identical
        # (retake +9.5 %); compile changes arithmetic (SNR >= 76 dB) and passed the owner's listening check;
        # compile-decode adds about 2 % with SNR >= 119 dB.
        self.assertEqual(adapter.DEFAULT_FEATURES, frozenset({"reference-cache", "condition-share", "compile", "compile-decode"}))


class RuntimePinTest(unittest.TestCase):
    def test_supported_runtimes_match_the_pinned_catalogue(self):
        from server.modules.tts_mlx_variants import MLX_RUNTIMES

        self.assertEqual(adapter.SUPPORTED_RUNTIMES, frozenset(MLX_RUNTIMES))


class RunTest(unittest.TestCase):
    def test_reports_profile_and_returns_generated_result(self):
        model = FakeModel()
        result, report = adapter.run(model, generate_kwargs(), runtime_version=RUNTIME, features=frozenset(), lora=False)
        self.assertEqual(result.sample_rate, 48000)
        self.assertEqual(report["optimizationProfile"], adapter.PROFILE)
        self.assertEqual(report["features"], [])
        self.assertIn("workerTotal", report["stageTimingsMs"])

    def test_failing_feature_restores_methods_and_retries_once_plainly(self):
        self.addCleanup(adapter.reset_failures)
        model = FakeModel()
        originals = (model.model.encode_conditions_full, model._encode_ref_audios, model.dacvae.decode)

        @contextlib.contextmanager
        def broken(model, kwargs, context):
            model.model.encode_conditions_full = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))
            try:
                yield
            finally:
                del model.model.encode_conditions_full

        def generate(**kwargs):
            model.generate_calls += 1
            model.model.encode_conditions_full()
            yield SimpleNamespace(audio=[0.0], sample_rate=48000)

        model.generate = generate
        with patch.dict(adapter.FEATURES, {"broken": broken}):
            result, report = adapter.run(model, generate_kwargs(), runtime_version=RUNTIME, features=frozenset({"broken"}), lora=False)
        self.assertEqual(result.sample_rate, 48000)
        self.assertEqual(report["optimizationProfile"], adapter.EAGER_PROFILE)
        self.assertEqual(report["fallbackReason"], "optimized-path-failed")
        self.assertIn("RuntimeError: boom", report["fallbackDetail"])
        self.assertEqual(model.generate_calls, 2)
        self.assertEqual(originals, (model.model.encode_conditions_full, model._encode_ref_audios, model.dacvae.decode))

    def test_unknown_feature_name_is_rejected(self):
        with self.assertRaises(ValueError):
            adapter.run(FakeModel(), generate_kwargs(), runtime_version=RUNTIME, features=frozenset({"typo"}), lora=False)

    def test_fallback_profile_calls_plain_generate_without_features(self):
        model = FakeModel()
        result, report = adapter.run(model, generate_kwargs(), runtime_version="mlx-audio@9.9.9", features=adapter.DEFAULT_FEATURES, lora=False)
        self.assertEqual(model.generate_calls, 1)
        self.assertEqual(report["features"], [])
        self.assertEqual(report["fallbackReason"], "unverified-runtime")


class FakeArray:
    nbytes = 1024


class ReferenceModel(FakeModel):
    def __init__(self):
        super().__init__()
        self.loads = 0
        self.encodes = 0

    def _load_ref_waveform(self, ref):
        self.loads += 1
        return FakeArray()

    def _encode_ref_audios(self, audios, max_ref_seconds=None):
        self.encodes += 1
        return (FakeArray(), FakeArray())

    def generate(self, **kwargs):
        ref = kwargs.get("ref_audio")
        if ref is not None:
            refs = ref if isinstance(ref, (list, tuple)) else [ref]
            self._encode_ref_audios([self._load_ref_waveform(item) for item in refs], max_ref_seconds=kwargs.get("max_ref_seconds"))
        yield SimpleNamespace(audio=[0.0], sample_rate=48000)


class ReferenceCacheTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        adapter.clear_caches()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.wav = f"{self.directory.name}/voice.wav"
        with open(self.wav, "wb") as handle:
            handle.write(b"first")

    def generate(self, model, ref):
        return adapter.run(model, {"text": "テスト", "ref_audio": ref}, runtime_version=RUNTIME,
                           features=frozenset({"reference-cache"}), lora=False)[1]

    def test_same_reference_file_is_loaded_and_encoded_once(self):
        model = ReferenceModel()
        self.generate(model, self.wav)
        report = self.generate(model, self.wav)
        self.assertEqual((model.loads, model.encodes), (1, 1))
        self.assertEqual(report["cacheStats"]["referenceCache"], "hit")

    def test_rewritten_reference_file_is_encoded_again(self):
        import os

        model = ReferenceModel()
        self.generate(model, self.wav)
        with open(self.wav, "wb") as handle:
            handle.write(b"second take")
        os.utime(self.wav, ns=(1, 1))
        self.generate(model, self.wav)
        self.assertEqual(model.encodes, 2)

    def test_in_memory_reference_is_never_cached(self):
        model = ReferenceModel()
        waveform = FakeArray()
        self.generate(model, waveform)
        report = self.generate(model, waveform)
        self.assertEqual(model.encodes, 2)
        self.assertEqual(report["cacheStats"].get("referenceCache"), "uncacheable")

    def test_methods_are_restored_after_the_call(self):
        model = ReferenceModel()
        self.generate(model, self.wav)
        self.assertNotIn("_encode_ref_audios", vars(model))
        self.assertNotIn("_load_ref_waveform", vars(model))


class ConditionInner:
    def __init__(self):
        self.encodes = 0
        self.kv_builds = 0

    def encode_conditions_full(self, text_input_ids, text_mask, ref_latent=None, ref_mask=None,
                               caption_input_ids=None, caption_mask=None):
        self.encodes += 1
        return (FakeArray(), text_mask, FakeArray(), ref_mask, FakeArray(), caption_mask)

    def build_kv_cache(self, text_state, speaker_state=None, caption_state=None):
        self.kv_builds += 1
        return ([FakeArray()], [FakeArray()], [FakeArray()])

    def forward_with_conditions(self, **kwargs):
        return "velocity"


class ConditionModel(FakeModel):
    """Mimics mlx-audio: duration and sampler both encode the same inputs, then the sampler builds KV."""

    def __init__(self):
        super().__init__()
        self.model = ConditionInner()
        self.seen_kv = []

    def generate(self, **kwargs):
        import numpy as np

        ids = np.frombuffer(kwargs["text"].encode("utf-8"), dtype=np.uint8).astype(np.int32)
        caption = np.frombuffer((kwargs.get("instruct") or "").encode("utf-8"), dtype=np.uint8).astype(np.int32)
        inputs = dict(text_input_ids=ids, text_mask=np.ones_like(ids, dtype=bool), ref_latent=np.zeros((1, 4)),
                      ref_mask=np.zeros((1, 4), dtype=bool), caption_input_ids=caption, caption_mask=np.ones_like(caption, dtype=bool))
        self.model.encode_conditions_full(**inputs)  # duration prediction
        conditions = self.model.encode_conditions_full(**inputs)  # sampler
        self.seen_kv.append(self.model.build_kv_cache(conditions[0], conditions[2], conditions[4]))
        yield SimpleNamespace(audio=[0.0], sample_rate=48000)


class ConditionShareTest(unittest.TestCase):
    def setUp(self):
        adapter.clear_caches()

    def generate(self, model, text="こんにちは", caption="明るく", seed=1):
        return adapter.run(model, {"text": text, "instruct": caption, "rng_seed": seed}, runtime_version=RUNTIME,
                           features=frozenset({"condition-share"}), lora=False)[1]

    def test_duration_and_sampler_share_one_encoding(self):
        model = ConditionModel()
        report = self.generate(model)
        self.assertEqual(model.model.encodes, 1)
        self.assertEqual(report["cacheStats"]["conditionCache"], "miss")
        self.assertTrue(report["cacheStats"]["conditionShared"])

    def test_retake_with_another_seed_reuses_conditions_and_kv(self):
        model = ConditionModel()
        self.generate(model, seed=1)
        report = self.generate(model, seed=2)
        self.assertEqual((model.model.encodes, model.model.kv_builds), (1, 1))
        self.assertIs(model.seen_kv[0], model.seen_kv[1])
        self.assertEqual(report["cacheStats"]["conditionCache"], "hit")
        self.assertEqual(report["cacheStats"]["kvCache"], "hit")

    def test_other_caption_or_text_does_not_reuse_conditions(self):
        model = ConditionModel()
        self.generate(model, caption="明るく")
        self.generate(model, caption="静かに")
        self.generate(model, text="さようなら", caption="静かに")
        self.assertEqual((model.model.encodes, model.model.kv_builds), (3, 3))

    def test_context_kv_never_evicts_conditions_on_a_small_budget(self):
        # On 16-32 GB Macs one real KV entry (~47-94 MB) is as large as the whole
        # condition budget; it must not push the small conditions out.
        model = ConditionModel()
        with patch.object(adapter._CONDITIONS, "limit", 3500):
            self.generate(model, seed=1)
            report = self.generate(model, seed=2)
        self.assertEqual((model.model.encodes, model.model.kv_builds), (1, 1))
        self.assertEqual((report["cacheStats"]["conditionCache"], report["cacheStats"]["kvCache"]), ("hit", "hit"))

    def test_only_the_latest_line_keeps_its_context_kv(self):
        model = ConditionModel()
        self.generate(model, text="一行目")
        self.generate(model, text="二行目")
        report = self.generate(model, text="一行目")
        self.assertEqual((model.model.encodes, model.model.kv_builds), (2, 3))
        self.assertEqual((report["cacheStats"]["conditionCache"], report["cacheStats"]["kvCache"]), ("hit", "miss"))

    def test_kv_for_states_other_than_the_shared_conditions_is_not_cached(self):
        model = ConditionModel()
        original_generate = model.generate

        def generate(**kwargs):
            model.seen_kv.append(model.model.build_kv_cache(FakeArray(), None, None))
            yield from original_generate(**kwargs)

        model.generate = generate
        self.generate(model, seed=1)
        self.generate(model, seed=2)
        # seen_kv: [unrelated, shared, unrelated, shared-reused]
        self.assertEqual(model.model.kv_builds, 3)
        self.assertIsNot(model.seen_kv[0], model.seen_kv[2])
        self.assertIs(model.seen_kv[1], model.seen_kv[3])


class CompileFeatureTest(unittest.TestCase):
    def setUp(self):
        adapter.clear_caches()
        self.compiled = []

        def fake_compile(function):
            self.compiled.append(function)
            return lambda **kwargs: ("compiled", function(**kwargs))

        patcher = patch.object(adapter, "_mx_compile", fake_compile)
        patcher.start()
        self.addCleanup(patcher.stop)

    def generate(self, model):
        def generate(**kwargs):
            model.last_velocity = model.model.forward_with_conditions(x_t=1)
            yield SimpleNamespace(audio=[0.0], sample_rate=48000)

        model.generate = generate
        return adapter.run(model, {"text": "テスト"}, runtime_version=RUNTIME, features=frozenset({"compile"}), lora=False)[1]

    def test_forward_is_compiled_once_and_reused_across_calls(self):
        model = FakeModel()
        self.generate(model)
        self.generate(model)
        self.assertEqual(len(self.compiled), 1)
        self.assertEqual(model.last_velocity, ("compiled", "velocity"))

    def test_forward_is_restored_after_the_call(self):
        model = FakeModel()
        self.generate(model)
        self.assertNotIn("forward_with_conditions", vars(model.model))

    def test_clearing_caches_drops_the_compiled_function(self):
        model = FakeModel()
        self.generate(model)
        adapter.clear_caches()
        self.generate(model)
        self.assertEqual(len(self.compiled), 2)


class StickyFallbackTest(unittest.TestCase):
    def setUp(self):
        adapter.clear_caches()
        self.addCleanup(adapter.reset_failures)

    def test_after_an_optimized_failure_later_calls_use_the_plain_path(self):
        @contextlib.contextmanager
        def broken(model, kwargs, context):
            raise RuntimeError("boom")
            yield

        model = FakeModel()
        with patch.dict(adapter.FEATURES, {"broken": broken}):
            first = adapter.run(model, generate_kwargs(), runtime_version=RUNTIME, features=frozenset({"broken"}), lora=False)[1]
            second = adapter.run(model, generate_kwargs(), runtime_version=RUNTIME, features=frozenset({"broken"}), lora=False)[1]
        self.assertEqual(first["fallbackReason"], "optimized-path-failed")
        self.assertEqual(second["fallbackReason"], "disabled-after-failure")
        # The feature fails before generating: one plain retry, then one plain call.
        self.assertEqual(model.generate_calls, 2)


class WorkerTestCase(unittest.TestCase):
    """Runs the worker with the default features on fake models.

    The default compile feature needs MLX, which the unit-test environment does
    not install, so compilation is replaced by the plain function here.
    """

    def setUp(self):
        adapter.clear_caches()
        adapter.reset_failures()
        patcher = patch.object(adapter, "_mx_compile", lambda function: function)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(adapter.reset_failures)


class WorkerPrepareTest(WorkerTestCase):
    def prepare(self, request):
        from server import mlx_irodori_worker as worker

        written = []
        model = FakeModel()
        with patch.object(worker, "RUNTIME_ENGINE_ID", RUNTIME), \
                patch.object(worker, "_write_wav", lambda path, audio, rate: written.append(path) or str(path)):
            outputs, execution = worker.synthesize(model, request)
        return model, outputs, written, execution

    def test_prepare_runs_one_discarded_generation(self):
        model, outputs, written, execution = self.prepare({
            "operation": "prepare", "text": "準備します。", "caption": None, "output": None, "seed": 0,
            "refWav": None, "steps": 1, "durationScale": 1.0, "numCandidates": 1,
            "textCfg": 3.0, "voiceCfg": 5.0, "captionCfg": 3.0, "schedule": "sway"})
        self.assertEqual((model.generate_calls, outputs, written), (1, [], []))
        self.assertIn("prewarmMs", execution["stageTimingsMs"])

    def test_prepare_without_cfg_fields_uses_defaults(self):
        # MeanFlow preparation requests carry no CFG or schedule fields.
        model, outputs, _written, _execution = self.prepare({
            "operation": "prepare", "text": "準備します。", "caption": None, "output": None, "seed": 0,
            "refWav": None, "steps": 4, "durationScale": 1.0, "numCandidates": 1})
        self.assertEqual((model.generate_calls, outputs), (1, []))


class WorkerWiringTest(WorkerTestCase):
    def test_worker_reports_acceleration_without_changing_runtime_identity(self):
        from server import mlx_irodori_worker as worker

        request = {"seed": 7, "numCandidates": 1, "output": "/tmp/scena-test.wav", "text": "テスト", "refWav": None,
                   "caption": None, "steps": 16, "textCfg": 3, "voiceCfg": 5, "captionCfg": 3, "schedule": "sway",
                   "durationScale": 1, "seconds": None}
        with patch.object(worker, "RUNTIME_ENGINE_ID", RUNTIME), patch.object(worker, "_write_wav", lambda path, audio, rate: str(path)):
            outputs, execution = worker._generate(FakeModel(), request, None)
        self.assertEqual(outputs, ["/tmp/scena-test.wav"])
        self.assertEqual(execution["optimizationProfile"], worker.OPTIMIZATION_PROFILE)
        self.assertEqual(execution["optimizationStats"]["accelerationProfile"], adapter.PROFILE)
        self.assertIsNone(execution["fallbackReason"])
        self.assertIn("workerTotal", execution["stageTimingsMs"])


if __name__ == "__main__":
    unittest.main()

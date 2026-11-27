"""Data integrity and request isolation at the actual adapter mutation boundary."""
import scena_test_isolation  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from server.scena_mlx_lora import (
    AdapterSession, BASE_REPO, BASE_REVISION, RestorationError, adapter_digest, build_updates, verify_base_checkpoint, install_empty_caption_compatibility, supports_lora_model, FP16_REPO, FP16_REVISION, verify_fp16_checkpoint,
)

TARGET = "model.blocks.0.attention.wq.weight"
DURATION = "model.duration_predictor.weight"
PREFIX = "base_model.model.blocks.0.attention.wq"
CONFIG = {"peft_type": "LORA", "bias": "none", "modules_to_save": ["duration_predictor"], "r": 1, "lora_alpha": 2}


class Arrays:
    float32 = np.float32
    float16 = np.float16
    all = staticmethod(np.all)
    isfinite = staticmethod(np.isfinite)

    @staticmethod
    def eval(*values):
        pass

    @staticmethod
    def load(path):
        raise AssertionError("Use the fixture load mock; never load pickle.")


class Model:
    def __init__(self):
        self.weights = {TARGET: np.ones((2, 2), dtype=np.float32), DURATION: np.ones((1, 2), dtype=np.float32)}
        self.fail_once = False
        self.fail_restore = False

    def parameters(self):
        return self.weights

    def load_weights(self, weights, strict=False):
        for key, value in weights:
            self.weights[key] = value
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("partial load failed")
        if self.fail_restore:
            raise RuntimeError("restore failed")


def adapter_weights():
    return {PREFIX + ".lora_A.weight": np.ones((1, 2), dtype=np.float32),
            PREFIX + ".lora_B.weight": np.ones((2, 1), dtype=np.float32),
            "base_model.model.duration_predictor.weight": np.zeros((1, 2), dtype=np.float32)}


class LoraMlxTests(unittest.TestCase):
    def test_all_tensors_are_consumed_and_base_is_unmodified_by_plan(self):
        model = Model()
        updates = build_updates(model.weights, adapter_weights(), CONFIG, Arrays)
        np.testing.assert_array_equal(updates[TARGET], np.full((2, 2), 3))
        self.assertNotIn(DURATION, updates)
        np.testing.assert_array_equal(model.weights[DURATION], np.ones((1, 2)))
        np.testing.assert_array_equal(model.weights[TARGET], np.ones((2, 2)))

    def test_unknown_missing_nonfinite_rank_and_quantized_rejected(self):
        cases = []
        unknown = adapter_weights()
        unknown["base_model.model.arbitrary.weight"] = np.ones(1)
        cases.append(unknown)
        missing = adapter_weights()
        del missing[PREFIX + ".lora_B.weight"]
        cases.append(missing)
        duration = adapter_weights()
        del duration["base_model.model.duration_predictor.weight"]
        cases.append(duration)
        invalid = adapter_weights()
        invalid[PREFIX + ".lora_A.weight"][0, 0] = np.nan
        cases.append(invalid)
        invalid_duration = adapter_weights()
        invalid_duration["base_model.model.duration_predictor.weight"][0, 0] = np.nan
        cases.append(invalid_duration)
        rank = adapter_weights()
        rank[PREFIX + ".lora_A.weight"] = np.ones((2, 2), dtype=np.float32)
        cases.append(rank)
        for weights in cases:
            with self.subTest(keys=list(weights)), self.assertRaises(ValueError):
                build_updates(Model().weights, weights, CONFIG, Arrays)
        model = Model()
        model.weights[TARGET] = model.weights[TARGET].astype(np.int16)
        with self.assertRaisesRegex(ValueError, "FP32"):
            build_updates(model.weights, adapter_weights(), CONFIG, Arrays)

    def test_fp16_updates_compute_in_fp32_and_store_and_restore_original_dtype(self):
        model = Model()
        model.weights = {key: value.astype(np.float16) for key, value in model.weights.items()}
        original = dict(model.weights)
        weights = adapter_weights()
        weights[PREFIX + ".lora_B.weight"] *= 0.0003
        updates = build_updates(model.weights, weights, CONFIG, Arrays)
        expected = (original[TARGET].astype(np.float32) + 2 * (weights[PREFIX + ".lora_B.weight"] @ weights[PREFIX + ".lora_A.weight"])).astype(np.float16)
        np.testing.assert_array_equal(updates[TARGET], expected)
        self.assertTrue(all(value.dtype == np.float16 for value in updates.values()))
        session = AdapterSession(model, arrays=Arrays, flatten=lambda values: values.items())
        session.changed = set(updates)
        model.load_weights(list(updates.items()))
        session.restore()
        for key in original:
            self.assertIs(model.weights[key], original[key])
            self.assertEqual(model.weights[key].dtype, np.float16)

    def test_fp16_runtime_requires_origin_and_exact_artifact_and_rejects_quantization(self):
        model = {"baseModelRepo": BASE_REPO, "baseModelRevision": BASE_REVISION,
                 "repo": FP16_REPO, "revision": FP16_REVISION, "backend": "mlx", "variantId": "mlx-fp16", "precision": "FP16"}
        self.assertTrue(supports_lora_model(model))
        for key, value in (("baseModelRevision", "unknown"), ("revision", "unknown"), ("quantization", {"bits": 8}), ("variantId", "mlx-8bit")):
            with self.subTest(key=key):
                self.assertFalse(supports_lora_model({**model, key: value}))

    def test_fp16_checkpoint_and_configuration_hashes_are_both_required(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            checkpoint = Path(temporary) / "model.safetensors"
            config = Path(temporary) / "config.json"
            checkpoint.write_bytes(b"weights")
            config.write_bytes(b"config")
            with patch("server.scena_mlx_lora.FP16_SHA256", hashlib.sha256(b"weights").hexdigest()), patch("server.scena_mlx_lora.FP16_CONFIG_SHA256", hashlib.sha256(b"config").hexdigest()):
                verify_fp16_checkpoint(checkpoint)
                config.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "config.json"):
                    verify_fp16_checkpoint(checkpoint)

    def test_whole_missing_attention_pair_is_rejected(self):
        model = Model()
        model.weights["model.blocks.0.attention.wk.weight"] = np.ones((2, 2), dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "attention target set"):
            build_updates(model.weights, adapter_weights(), CONFIG, Arrays)

    def test_unsupported_peft_configuration_fails_closed(self):
        for field in ("use_dora", "use_rslora", "use_qalora", "fan_in_fan_out", "lora_bias"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                build_updates(Model().weights, adapter_weights(), {**CONFIG, field: True}, Arrays)

    def test_on_off_exception_and_partial_load_restore_exact_base(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "adapter_config.json").write_text(json.dumps(CONFIG))
            (directory / "adapter_model.safetensors").write_bytes(b"fixture-not-read")
            descriptor = {"path": str(directory), "adapterHash": adapter_digest(directory),
                          "baseModelRepo": BASE_REPO, "baseModelRevision": BASE_REVISION}
            model = Model()
            original = dict(model.weights)
            session = AdapterSession(model, arrays=Arrays, flatten=lambda weights: weights.items())
            with patch.object(Arrays, "load", return_value=adapter_weights()):
                for fail in (False, True):
                    try:
                        with session.scoped(descriptor):
                            self.assertFalse(np.array_equal(model.weights[TARGET], original[TARGET]))
                            self.assertIs(model.weights[DURATION], original[DURATION])
                            self.assertNotIn(DURATION, session.changed)
                            if fail:
                                raise RuntimeError("generation failed")
                    except RuntimeError:
                        self.assertTrue(fail)
                    for key in original:
                        self.assertIs(model.weights[key], original[key])
                with session.scoped(None):
                    self.assertIs(model.weights[TARGET], original[TARGET])
                model.fail_once = True
                with self.assertRaisesRegex(RuntimeError, "partial load"):
                    with session.scoped(descriptor):
                        self.fail("Must not generate")
                for key in original:
                    self.assertIs(model.weights[key], original[key])
                descriptor["adapterHash"] = "0" * 64
                with self.assertRaisesRegex(ValueError, "hash"):
                    with session.scoped(descriptor):
                        self.fail("Must not generate")

    def test_checkpoint_hash_validation_rejects_corrupt_and_missing_base(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.safetensors"
            with self.assertRaisesRegex(ValueError, "missing"):
                verify_base_checkpoint(path)
            path.write_bytes(b"validated fixture")
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            with patch("server.scena_mlx_lora.BASE_SHA256", expected):
                verify_base_checkpoint(path)
                path.write_bytes(b"changed fixture")
                with self.assertRaisesRegex(ValueError, "hash"):
                    verify_base_checkpoint(path)

    def test_restoration_failure_is_fatal(self):
        model = Model()
        session = AdapterSession(model, arrays=Arrays, flatten=lambda weights: weights.items())
        session.changed = {TARGET}
        model.fail_restore = True
        with self.assertRaises(RestorationError):
            session.restore()
        self.assertEqual(session.changed, {TARGET})


if __name__ == "__main__":
    unittest.main()


class EmptyCaptionCompatibilityTests(unittest.TestCase):
    def test_absent_condition_is_zero_and_normal_caption_passes_through(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        arrays = SimpleNamespace(any=np.any, zeros=np.zeros)
        expected = np.ones((1, 2, 4), dtype=np.float32)
        encoder = Mock(return_value=expected)
        inner = SimpleNamespace(_encode_caption=encoder, cfg=SimpleNamespace(caption_dim_resolved=4),
                                caption_norm=SimpleNamespace(weight=np.ones(4, dtype=np.float32)))
        model = SimpleNamespace(model=inner)
        install_empty_caption_compatibility(model, arrays=arrays)
        ids = np.ones((1, 2), dtype=np.int32)
        absent_mask = np.zeros((1, 2), dtype=bool)
        empty = inner._encode_caption(ids, absent_mask)
        np.testing.assert_array_equal(empty, np.zeros((1, 2, 4)))
        self.assertTrue(np.isfinite(empty).all())
        np.testing.assert_array_equal(absent_mask, np.zeros((1, 2), dtype=bool))
        encoder.assert_not_called()
        present_mask = np.ones((1, 2), dtype=bool)
        self.assertIs(inner._encode_caption(ids, present_mask), expected)
        encoder.assert_called_once_with(ids, present_mask)
        current = inner._encode_caption
        install_empty_caption_compatibility(model, arrays=arrays)
        self.assertIs(inner._encode_caption, current)

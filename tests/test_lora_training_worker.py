from __future__ import annotations
from contextlib import nullcontext
import importlib
from unittest.mock import MagicMock, patch
import unittest
import numpy as np
from server import lora_training_compat

with patch.dict("sys.modules", {"lora_training_compat": lora_training_compat}):
    worker = importlib.import_module("server.lora_training_worker")


class LoraTrainingWorkerTests(unittest.TestCase):
    def test_pcm_stays_cpu_until_codec_resampling_and_loudness_preprocessing(self):
        # The API environment deliberately has no torch. This boundary mock
        # catches the regression of moving source PCM to MPS before audiotools.
        torch = MagicMock()
        cpu_tensor = MagicMock()
        torch.from_numpy.return_value.reshape.return_value = cpu_tensor
        torch.inference_mode.return_value = nullcontext()
        codec = MagicMock()
        latent = MagicMock()
        codec.encode_waveform.return_value = [latent]
        audio = np.asarray([[0.25, 0.75], [-0.5, 0.5]], dtype=np.float32)
        with patch.dict("sys.modules", {"torch": torch}):
            result = worker.encode_cpu_pcm(codec, audio, 44100)
        np.testing.assert_array_equal(torch.from_numpy.call_args.args[0], [0.5, 0.0])
        cpu_tensor.to.assert_not_called()
        codec.encode_waveform.assert_called_once_with(cpu_tensor, sample_rate=44100)
        self.assertIs(result, latent.cpu.return_value)

    def test_continuation_verifies_frozen_bytes_before_loading_and_rejects_changes(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            adapter = directory / "source-adapter"
            adapter.mkdir()
            (adapter / "adapter_config.json").write_bytes(b"config")
            (adapter / "adapter_model.safetensors").write_bytes(b"weights")
            request = {"sourceAdapter": {"configHash": worker.file_hash(adapter / "adapter_config.json"),
                       "weightsHash": worker.file_hash(adapter / "adapter_model.safetensors")}}
            self.assertEqual(worker.continuation_path(directory, request), str(adapter))
            self.assertIsNone(worker.continuation_path(directory, {}))
            (adapter / "adapter_model.safetensors").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "Frozen source"):
                worker.continuation_path(directory, request)

    def test_continuation_initializes_trainable_adapter_with_fresh_optimizer(self):
        import hashlib
        source = ("dtype=torch.float64 " * 4 + ".double() " * 7 + "\n"
                  "                optimizer.step()\n"
                  "        if train_config_uses_lora(train_cfg) and not lora_wrapped:\n"
                  "            raw_model = apply_lora(raw_model, train_cfg)\n")
        with patch.object(lora_training_compat, "TRAIN_SHA256", hashlib.sha256(source.encode()).hexdigest()):
            adapted = lora_training_compat.compatible_trainer(source.encode(), '/owned/source-adapter')
            self.assertIn('load_lora_adapter(raw_model, Path("/owned/source-adapter"), is_trainable=True)', adapted)
            self.assertNotIn('apply_lora(raw_model, train_cfg)', adapted)
            self.assertNotIn('optimizer.load_state_dict', adapted)
            ordinary = lora_training_compat.compatible_trainer(source.encode())
            self.assertIn('apply_lora(raw_model, train_cfg)', ordinary)

    def test_continuation_config_keeps_adapter_architecture_and_uses_additional_steps(self):
        import json
        import tempfile
        from pathlib import Path
        import yaml
        safe = MagicMock()
        safe.safe_open.return_value.__enter__.return_value.metadata.return_value = {"config_json": "{}"}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "configs").mkdir()
            (directory / "configs/train_v4_small_lora.yaml").write_text(yaml.safe_dump({"model": {}, "train": {}}))
            (directory / "source-adapter").mkdir()
            adapter = {"r": 8, "lora_alpha": 16, "lora_dropout": 0.05, "target_modules": "attention", "modules_to_save": ["duration_predictor"]}
            (directory / "source-adapter/adapter_config.json").write_text(json.dumps(adapter))
            (directory / "manifest.jsonl").write_text(json.dumps({"num_frames": 75}) + "\n")
            request = {"sourceAdapter": {"assetId": "source"}, "runtime": {"enginePath": temp, "checkpoint": "base"},
                       "settings": {"maxSteps": 12, "batchSize": 1, "maxSeconds": 3, "learningRate": 0.0001}, "rows": [{}]}
            with patch.dict("sys.modules", {"safetensors": safe}):
                path = worker.configure(directory, request)
            train = yaml.safe_load(path.read_text())["train"]
            self.assertEqual(train["lora_r"], 8)
            self.assertEqual(train["lora_alpha"], 16)
            self.assertEqual(train["lora_modules_to_save"], ["duration_predictor"])
            self.assertEqual(train["max_steps"], 12)

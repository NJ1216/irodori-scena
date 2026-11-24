from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import inference, runtime_state


class WorkerExchangeContractTests(unittest.TestCase):
    def worker(self, response):
        read_fd, write_fd = os.pipe()
        with os.fdopen(write_fd, "w") as writer:
            writer.write("diagnostic\n" + runtime_state.WORKER_RESULT_PREFIX + json.dumps(response) + "\n")
        stdout = os.fdopen(read_fd, "r")
        self.addCleanup(stdout.close)
        return SimpleNamespace(stdin=io.StringIO(), stdout=stdout)


    def test_preparation_request_is_unsaved_and_records_memory(self):
        worker = self.worker({"ok": True, "metrics": {"mpsDriverAllocatedBytes": 123}})
        with patch("server.modules.resource_coordinator.acquire_tts_memory"), patch.object(inference, "engine_dir", return_value=Path("/engine")), patch.object(
            inference, "inference_worker_locked", return_value=worker,
        ), patch.object(inference, "INFERENCE_METAL_BYTES", None):
            self.assertIsNone(inference.prepare_irodori_worker())
            self.assertEqual(inference.INFERENCE_METAL_BYTES, 123)
        self.assertEqual(json.loads(worker.stdin.getvalue()), {
            "operation": "prepare", "text": "準備します。", "caption": None, "output": None,
            "seed": 0, "refWav": None, "steps": 1, "textCfg": 3.0, "voiceCfg": 5.0,
            "captionCfg": 3.0, "durationScale": 1.0, "schedule": "sway", "numCandidates": 1,
        })

    def test_synthesis_payload_outputs_and_execution_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "take.wav"
            output.write_bytes(b"fixture")
            execution = {"optimizationProfile": "scena-mps", "stageTimingsMs": {"sample": 12}}
            worker = self.worker({"ok": True, "outputs": [str(output)], "execution": execution,
                                  "metrics": {"mpsDriverAllocatedBytes": 456}})
            with patch("server.modules.resource_coordinator.acquire_tts_memory"), patch.object(inference, "engine_dir", return_value=Path("/engine")), patch.object(
                inference, "inference_worker_locked", return_value=worker,
            ), patch.object(inference, "INFERENCE_METAL_BYTES", None), patch.object(inference, "LAST_INFERENCE_EXECUTION", {}), patch(
                "server.modules.tts_registry.selected_tts_runtime",
                return_value={"model": {"variantId": "pytorch-fp32", "backend": "pytorch", "repo": "official-model", "revision": "model-revision", "precision": "FP32"}},
            ):
                result = inference._run_irodori(text="本文", caption="静かに", output=output,
                                              seed=42, ref_wav=Path("/reference.wav"), quality="fast")
                self.assertEqual(result, [output])
                self.assertEqual(inference.last_inference_execution(), {
                    **execution,
                    "variantId": "pytorch-fp32",
                    "backend": "pytorch",
                    "artifactRepo": "official-model",
                    "artifactRevision": "model-revision",
                    "precision": "FP32",
                })
                self.assertEqual(inference.INFERENCE_METAL_BYTES, 456)
            self.assertEqual(json.loads(worker.stdin.getvalue()), {
                "operation": "synthesize", "text": "本文", "caption": "静かに", "output": str(output),
                "seed": 42, "refWav": str(Path("/reference.wav")), "steps": 16, "textCfg": 3.0, "voiceCfg": 5.0,
                "captionCfg": 3.0, "durationScale": 0.8333, "seconds": None, "schedule": "sway", "numCandidates": 1, "loraAdapter": None,
            })

    def test_meanflow_payload_is_fixed_to_four_steps_without_rf_controls(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "take.wav"
            output.write_bytes(b"fixture")
            worker = self.worker({"ok": True, "outputs": [str(output)], "execution": {}})
            capabilities = {"flowParameterization": "meanflow", "fixedSteps": 4, "supportsRuntimeCfg": False}
            with patch.object(inference, "engine_dir", return_value=Path("/engine")), patch.object(
                inference, "inference_worker_locked", return_value=worker,
            ), patch("server.modules.tts_registry.selected_model_capabilities", return_value=capabilities):
                inference._run_irodori(
                    text="本文", caption="静かに", output=output, seed=42, ref_wav=None, quality="quality",
                    generation_settings={"steps": 40, "textCfg": 9, "voiceCfg": 9, "captionCfg": 9},
                )
            payload = json.loads(worker.stdin.getvalue())
            self.assertEqual(payload["steps"], 4)
            self.assertTrue({"textCfg", "voiceCfg", "captionCfg", "schedule"}.isdisjoint(payload))

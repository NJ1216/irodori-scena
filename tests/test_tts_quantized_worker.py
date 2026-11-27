from __future__ import annotations

import scena_test_isolation  # noqa: F401
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import inference, runtime_state


def _pytorch_runtime(root: Path) -> tuple[Path, Path, dict]:
    engine, model, codec = root / "engine", root / "model", root / "codec"
    checkpoint, tokenizer = model / "int8-weight-only" / "model.safetensors", model / "tokenizer"
    checkpoint.parent.mkdir(parents=True)
    tokenizer.mkdir()
    engine.mkdir()
    codec.mkdir()
    checkpoint.write_bytes(b"model")
    (codec / "weights.pth").write_bytes(b"codec")
    python = root / "python"
    python.write_text("", encoding="utf-8")
    runtime = {"engine": {"pythonPath": str(python), "commit": "engine"}, "model": {
        "path": str(model), "codecPath": str(codec), "repo": "Aratako/Irodori-TTS-v4.1-Small-Quantized",
        "revision": "revision", "variantId": "pytorch-w8a16", "backend": "pytorch",
        "checkpointFile": "int8-weight-only/model.safetensors", "computePrecision": "bf16",
    }}
    return engine, checkpoint, runtime


def _worker_environment(engine: Path, runtime: dict) -> dict:
    with patch.object(runtime_state, "INFERENCE_WORKER", None), patch(
        "server.modules.tts_registry.selected_tts_runtime", return_value=runtime
    ), patch.object(inference.subprocess, "Popen") as popen:
        inference.inference_worker_locked(engine)
    return popen.call_args.kwargs["env"]


class QuantizedWorkerTests(unittest.TestCase):
    def test_physical_core_count_is_passed_for_cpu_inference(self) -> None:
        for cores, expected in [(8, "8"), (None, None)]:
            with self.subTest(cores=cores), tempfile.TemporaryDirectory() as temporary:
                engine, _, runtime = _pytorch_runtime(Path(temporary))
                with patch.object(inference.psutil, "cpu_count", return_value=cores) as count, patch.dict(inference.os.environ, {}, clear=False):
                    inference.os.environ.pop("IRODORI_TTS_CPU_THREADS", None)
                    environment = _worker_environment(engine, runtime)
                count.assert_called_with(logical=False)
                self.assertEqual(environment.get("IRODORI_TTS_CPU_THREADS"), expected)

    def test_cuda_calibration_store_lives_in_the_data_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            engine, _, runtime = _pytorch_runtime(Path(temporary))
            with patch("server.modules.constants.DATA_ROOT", Path(temporary) / "data"):
                environment = _worker_environment(engine, runtime)
            self.assertEqual(environment["IRODORI_TTS_CUDA_CALIBRATION"], str(Path(temporary) / "data" / "tts" / "cuda-acceleration-calibration.json"))

    def test_subfolder_checkpoint_and_bf16_are_passed_to_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine, model, codec = root / "engine", root / "model", root / "codec"
            checkpoint, tokenizer = model / "int8-weight-only" / "model.safetensors", model / "tokenizer"
            checkpoint.parent.mkdir(parents=True)
            tokenizer.mkdir()
            engine.mkdir()
            codec.mkdir()
            checkpoint.write_bytes(b"model")
            (codec / "weights.pth").write_bytes(b"codec")
            python = root / "python"
            python.write_text("", encoding="utf-8")
            runtime = {"engine": {"pythonPath": str(python), "commit": "engine"}, "model": {
                "path": str(model), "codecPath": str(codec), "repo": "Aratako/Irodori-TTS-v4.1-Small-Quantized",
                "revision": "revision", "variantId": "pytorch-w8a16", "backend": "pytorch",
                "checkpointFile": "int8-weight-only/model.safetensors", "computePrecision": "bf16",
            }}
            with patch.object(runtime_state, "INFERENCE_WORKER", None), patch(
                "server.modules.tts_registry.selected_tts_runtime", return_value=runtime
            ), patch.object(inference.subprocess, "Popen") as popen:
                inference.inference_worker_locked(engine)
            environment = popen.call_args.kwargs["env"]
            self.assertEqual(environment["IRODORI_TTS_CHECKPOINT"], str(checkpoint))
            self.assertEqual(environment["IRODORI_TTS_COMPUTE_PRECISION"], "bf16")
            self.assertEqual(environment["IRODORI_TTS_VARIANT_ID"], "pytorch-w8a16")


if __name__ == "__main__":
    unittest.main()

"""Execution metadata must stay with its request after the synthesis lock releases."""
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import inference


class ExecutionIsolationTests(unittest.TestCase):
    def test_another_request_cannot_overwrite_returned_execution(self):
        a_returned, b_returned = threading.Event(), threading.Event()
        results, failures = {}, []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = {"model": {"variantId": "mlx-fp32", "backend": "mlx", "precision": "FP32"}}
            dependencies = SimpleNamespace(
                selected_tts_runtime=lambda: runtime, selected_model_capabilities=lambda: {},
                normalize_target_duration=lambda value: None, INFERENCE_WORKER_LOCK=threading.Lock(),
                set_worker_background=lambda worker, background: None,
            )

            def response(worker, request, cancel):
                Path(request["output"]).touch()
                return {"outputs": [request["output"]], "execution": {"lora": {"adapterHash": str(request["seed"])}}}

            def generate(name, seed):
                try:
                    if name == "b":
                        self.assertTrue(a_returned.wait(2))
                    inference._run_irodori(text="fixture", caption=None, output=root / f"{name}.wav",
                                           seed=seed, ref_wav=None, quality="fast")
                    if name == "a":
                        a_returned.set()
                        self.assertTrue(b_returned.wait(2))
                    else:
                        b_returned.set()
                    results[name] = inference.last_inference_execution()
                except Exception as error:
                    failures.append(error)
                    a_returned.set()
                    b_returned.set()

            with patch.object(inference, "deps", dependencies), patch.object(inference, "engine_dir", return_value=root), patch.object(inference, "inference_worker_locked", return_value=object()), patch.object(inference, "_exchange_response", side_effect=response):
                threads = [threading.Thread(target=generate, args=("a", 1)), threading.Thread(target=generate, args=("b", 2))]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(results["a"]["lora"]["adapterHash"], "1")
        self.assertEqual(results["b"]["lora"]["adapterHash"], "2")


class WorkerCodecMetadataTests(unittest.TestCase):
    def test_fp32_execution_records_actual_codec_separately_from_base(self):
        from server import mlx_irodori_worker as worker
        environment = {"IRODORI_TTS_CODEC_ARTIFACT_REPO": "mlx-community/Irodori-TTS-v4.1-Small-fp16",
                       "IRODORI_TTS_CODEC_ARTIFACT_REVISION": "8be8d91091380115f1ac77aeb6604ed588d05372",
                       "IRODORI_TTS_BASE_REPO": "Aratako/Irodori-TTS-v4.1-Small",
                       "IRODORI_TTS_BASE_REVISION": "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"}
        with patch.object(worker, "VARIANT_ID", "mlx-fp32"), patch.object(worker, "PRECISION", "FP32"), patch.object(worker, "CODEC_PRECISION", "fp32"), patch.dict(worker.os.environ, environment):
            metadata = worker._execution({"adapterHash": "fixture"})
        self.assertEqual(metadata["precision"], "FP32")
        self.assertEqual(metadata["artifactRepo"], environment["IRODORI_TTS_BASE_REPO"])
        self.assertEqual(metadata["codec"], {"repo": environment["IRODORI_TTS_CODEC_ARTIFACT_REPO"],
                                            "revision": environment["IRODORI_TTS_CODEC_ARTIFACT_REVISION"],
                                            "precision": "fp32"})
        self.assertEqual(metadata["lora"]["baseModelRepo"], environment["IRODORI_TTS_BASE_REPO"])


class WorkerAudioEncodingTests(unittest.TestCase):
    def test_codec_float16_audio_is_normalized_before_pcm16_writer(self):
        import sys
        import wave
        import numpy as np
        from server import mlx_irodori_worker as worker
        received = []

        def write(path, samples, sample_rate):
            received.append(samples.dtype)
            # Reproduce the pinned writer's dtype-dependent conversion.
            pcm = (samples * 32767).astype(np.int16) if samples.dtype in (np.float32, np.float64) else samples.astype(np.int16)
            with wave.open(path, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(pcm.tobytes())

        audio_io = SimpleNamespace(write=write)
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, {"mlx_audio.audio_io": audio_io}):
            path = Path(temporary) / "float16.wav"
            worker._write_wav(path, np.array([0.25, -0.25, 0.5], dtype=np.float16), 48000)
            with wave.open(str(path)) as wav:
                samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
            self.assertEqual(received, [np.dtype(np.float32)])
            self.assertTrue(np.any(samples))
            np.testing.assert_array_equal(samples, [8191, -8191, 16383])

    def test_empty_nonfinite_and_pcm_silence_are_rejected_before_writing(self):
        import sys
        import numpy as np
        from server import mlx_irodori_worker as worker
        from unittest.mock import Mock
        writer = Mock()
        with tempfile.TemporaryDirectory() as temporary, patch.dict(sys.modules, {"mlx_audio.audio_io": SimpleNamespace(write=writer)}):
            path = Path(temporary) / "invalid.wav"
            for samples in (np.array([]), np.array([np.nan]), np.zeros(10), np.full(10, 1e-8)):
                with self.subTest(samples=samples), self.assertRaises(ValueError):
                    worker._write_wav(path, samples, 48000)
            writer.assert_not_called()
            self.assertFalse(path.exists())


class Fp16ExecutionIdentityTests(unittest.TestCase):
    def test_origin_and_fp16_artifact_are_separate(self):
        from server import mlx_irodori_worker as worker
        from server.scena_mlx_lora import BASE_REPO, BASE_REVISION, FP16_REPO, FP16_REVISION
        environment = {"IRODORI_TTS_BASE_REPO": BASE_REPO, "IRODORI_TTS_BASE_REVISION": BASE_REVISION,
                       "IRODORI_TTS_ARTIFACT_REPO": FP16_REPO, "IRODORI_TTS_ARTIFACT_REVISION": FP16_REVISION}
        with patch.object(worker, "VARIANT_ID", "mlx-fp16"), patch.object(worker, "PRECISION", "FP16"), patch.dict(worker.os.environ, environment):
            execution = worker._execution({"adapterHash": "fixture"})
        self.assertEqual(execution["artifactRepo"], FP16_REPO)
        self.assertEqual(execution["artifactRevision"], FP16_REVISION)
        self.assertEqual(execution["lora"]["baseModelRepo"], BASE_REPO)
        self.assertEqual(execution["lora"]["baseModelRevision"], BASE_REVISION)
        self.assertEqual(execution["lora"]["artifactRepo"], FP16_REPO)
        self.assertEqual(execution["lora"]["precision"], "FP16")

from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import server.app  # noqa: F401
from server.modules import llama_cpp_runtime as runtime


def archive(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for name, content in files.items():
            target.writestr(name, content)
    return output.getvalue()


class LlamaCppRuntimeTests(unittest.TestCase):
    def test_binary_archive_without_license_fetches_pinned_license(self):
        for valid in (True, False):
            with self.subTest(valid=valid), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = archive({"llama-server.exe": b"exe"})
                license_text = b"official license"
                spec = {"version": "test", "required": ["llama-server.exe", "LICENSE"],
                        "license": {"url": "https://example.invalid/LICENSE",
                                    "sha256": hashlib.sha256(license_text).hexdigest()},
                        "backends": {"cpu": {"artifacts": [{"url": "https://example.invalid/bin.zip",
                                     "sha256": hashlib.sha256(binary).hexdigest()}]}}}
                runtime.CANCEL.clear()
                with patch.object(runtime, "_root", return_value=root), \
                        patch.object(runtime, "_manifest", return_value=spec), \
                        patch.object(runtime.urllib.request, "urlopen", side_effect=[
                            io.BytesIO(binary), io.BytesIO(license_text if valid else b"corrupt")]):
                    runtime._install("cpu")
                    self.assertEqual(runtime.llama_cpp_runtime_status("cpu")["ready"], valid)
                self.assertEqual(runtime.JOB["state"], "complete" if valid else "failed")
                if valid:
                    self.assertEqual((root / "test-cpu/LICENSE").read_bytes(), license_text)

    def test_backend_selection_prefers_cuda_and_persists_the_choice(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(runtime, "_root", return_value=Path(directory)), \
                patch.object(runtime, "nvidia_available", return_value=True), \
                patch.object(runtime, "_manifest", return_value={"version": "test"}):
            result = runtime.select_llama_cpp_backend("cuda")
            self.assertEqual(result["backend"], "cuda")
            self.assertEqual(runtime.selected_backend(), "cuda")

    def test_backend_selection_does_not_fall_back_from_unavailable_cuda(self):
        with patch.object(runtime, "nvidia_available", return_value=False):
            with self.assertRaises(HTTPException) as raised:
                runtime.select_llama_cpp_backend("cuda")
        self.assertEqual(raised.exception.status_code, 409)

    def test_safe_extract_keeps_runtime_files_and_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good = root / "good.zip"
            good.write_bytes(archive({"bin/llama-server.exe": b"exe", "bin/ggml.dll": b"dll", "tool.exe": b"tool", "LICENSE": b"mit"}))
            staging = root / "staging"
            staging.mkdir()
            runtime._safe_extract(good, staging)
            self.assertEqual(sorted(path.name for path in staging.iterdir()), ["LICENSE", "ggml.dll", "llama-server.exe"])
            bad = root / "bad.zip"
            bad.write_bytes(archive({"../llama-server.exe": b"bad"}))
            with self.assertRaises(ValueError):
                runtime._safe_extract(bad, staging)

    def test_hash_mismatch_removes_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / "runtime.zip.partial"
            class Response(io.BytesIO):
                status = 200
                def __enter__(self): return self
                def __exit__(self, *_args): self.close()
            runtime.CANCEL.clear()
            runtime.JOB["downloadedBytes"] = 0
            with patch.object(runtime.urllib.request, "urlopen", return_value=Response(b"wrong")):
                with self.assertRaises(ValueError):
                    runtime._download("https://example.invalid/runtime.zip", "0" * 64, partial)
            self.assertFalse(partial.exists())

    def test_cancel_keeps_partial_for_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / "runtime.zip.partial"
            class Response:
                status = 200
                def __enter__(self): return self
                def __exit__(self, *_args): pass
                def read(self, _size):
                    runtime.CANCEL.set()
                    return b"chunk"
            runtime.CANCEL.clear()
            runtime.JOB["downloadedBytes"] = 0
            with patch.object(runtime.urllib.request, "urlopen", return_value=Response()):
                with self.assertRaises(InterruptedError):
                    runtime._download("https://example.invalid/runtime.zip", hashlib.sha256(b"chunk").hexdigest(), partial)
            self.assertTrue(partial.exists())
            runtime.CANCEL.clear()

    def test_install_publishes_only_verified_runtime_and_removes_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "payload.zip"
            payload.write_bytes(archive({"llama-server.exe": b"exe", "ggml.dll": b"dll", "LICENSE": b"mit"}))
            spec = {"version": "test", "required": ["llama-server.exe", "LICENSE"],
                    "backends": {"cpu": {"artifacts": [{"url": "u", "sha256": "h"}]}}}
            runtime.JOB.clear()
            runtime.JOB["state"] = "queued"
            with patch.object(runtime, "_root", return_value=root / "runtimes"), \
                    patch.object(runtime, "_manifest", return_value=spec), \
                    patch.object(runtime, "_download", return_value=payload):
                runtime._install("cpu")
            target = root / "runtimes" / "test-cpu"
            self.assertTrue((target / ".ready").is_file())
            self.assertFalse(payload.exists())
            self.assertEqual(runtime.JOB["state"], "complete")

    def test_failed_install_keeps_previous_ready_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtimes = root / "runtimes"
            target = runtimes / "test-cpu"
            target.mkdir(parents=True)
            (target / ".ready").write_text("old")
            payload = root / "payload.zip"
            payload.write_bytes(archive({"llama-server.exe": b"exe"}))
            spec = {"version": "test", "required": ["llama-server.exe", "LICENSE"],
                    "backends": {"cpu": {"artifacts": [{"url": "u", "sha256": "h"}]}}}
            runtime.JOB.clear()
            runtime.JOB["state"] = "queued"
            with patch.object(runtime, "_root", return_value=runtimes), \
                    patch.object(runtime, "_manifest", return_value=spec), \
                    patch.object(runtime, "_download", return_value=payload):
                runtime._install("cpu")
            self.assertEqual((target / ".ready").read_text(), "old")
            self.assertEqual(runtime.JOB["state"], "failed")

    def test_delete_requires_all_local_models_to_be_removed(self):
        runtime.JOB.clear()
        runtime.JOB["state"] = "complete"
        with patch("server.modules.llm_registry.read_llm_registry", return_value={"cards": [{"source": "managed"}]}):
            with self.assertRaises(HTTPException) as raised:
                runtime.delete_llama_cpp_runtime("cpu")
        self.assertEqual(raised.exception.status_code, 409)

    def test_delete_removes_an_unreferenced_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "test-cpu"
            target.mkdir()
            (target / ".ready").write_text("ready")
            runtime.JOB.clear()
            runtime.JOB["state"] = "complete"
            with patch.object(runtime, "_root", return_value=root), \
                    patch.object(runtime, "_manifest", return_value={"version": "test"}), \
                    patch("server.modules.llm_registry.read_llm_registry", return_value={"cards": []}), \
                    patch("server.modules.local_llm_runtime.stop_local_llm"):
                result = runtime.delete_llama_cpp_runtime("cpu")
            self.assertFalse(target.exists())
            self.assertFalse(result["ready"])

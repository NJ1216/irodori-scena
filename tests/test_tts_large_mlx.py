from __future__ import annotations

import copy
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import tts_downloads, tts_registry
from server.modules.tts_catalog import tts_catalog
from server.modules.tts_mlx_variants import LARGE_MLX_COMMIT, LARGE_MLX_PACKAGE, mlx_engine_id


class LargeMlxTests(unittest.TestCase):
    def setUp(self):
        with patch("server.modules.tts_catalog.sys.platform", "darwin"), patch(
            "server.modules.tts_catalog.platform.machine", return_value="arm64"
        ):
            self.large = next(m for m in tts_catalog()["models"] if m["repo"] == "Aratako/Irodori-TTS-v4-Large")
        self.variants = [v for v in self.large["variants"] if v["backend"] == "mlx"]

    def test_large_uses_real_bf16_and_8bit_artifacts_and_separate_runtime(self):
        self.assertEqual([v["id"] for v in self.variants], ["mlx-bf16", "mlx-8bit"])
        self.assertEqual([v["precision"] for v in self.variants], ["BF16", "8bit"])
        self.assertEqual([v["sizeBytes"] for v in self.variants], [7039437071 + 14490, 4470479606 + 14490])
        self.assertEqual(min((v for v in self.large["variants"] if v["available"]), key=lambda v: v["recommendedOrder"])["id"], "mlx-bf16")
        for variant in self.variants:
            self.assertEqual(variant["runtimePackage"], LARGE_MLX_PACKAGE)
            self.assertEqual(mlx_engine_id(variant), f"mlx-audio@{LARGE_MLX_COMMIT}")
            artifacts = {entry["path"]: entry["sha256"] for entry in variant["artifactFiles"]}
            self.assertEqual(set(artifacts), set(variant["downloadFiles"]))
            self.assertEqual(artifacts["model.safetensors"], variant["modelSha256"])
            self.assertEqual(artifacts["tokenizer/tokenizer.json"], "f5b325224482ec441ec5fbe2a5ac08c3758e0f9605f6e54368e31f736fcfb01d")
            self.assertEqual(set(variant["auxiliaryAssets"]["downloadFiles"]), {"NOTICE", "GEMMA_TERMS_OF_USE.md", "GEMMA_PROHIBITED_USE_POLICY.md"})

    def test_large_environment_install_does_not_reuse_or_modify_small_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            small = root / "environments/mlx-audio-0.5.0/bin/python"
            small.parent.mkdir(parents=True)
            small.write_text("existing")
            calls = []

            def run(command, **_options):
                calls.append(command)
                if command[1] == "venv":
                    python = Path(command[-1]) / "bin/python"
                    python.parent.mkdir(parents=True)
                    python.write_text("large")

            with patch.object(tts_downloads, "deps", SimpleNamespace(
                TTS_ENVIRONMENTS_ROOT=root / "environments", TTS_DOWNLOADS_ROOT=root / "downloads",
            )), patch.object(tts_downloads, "_uv_binary", return_value="uv"), patch.object(
                tts_downloads, "run_environment_command", side_effect=run
            ):
                python = tts_downloads._ensure_mlx_environment({}, threading.Event(), self.variants[0])
                self.assertEqual(tts_downloads._ensure_mlx_environment({}, threading.Event(), self.variants[1]), python)
            self.assertIn(LARGE_MLX_PACKAGE, calls[1])
            self.assertEqual(len(calls), 2)
            self.assertEqual(small.read_text(), "existing")
            self.assertEqual(python.read_text(), "large")

    def test_selected_large_runtime_and_switch_preserve_small_engine(self):
        variant = {**self.variants[0], "path": "/large", "pythonPath": "/large-python"}
        engine_id = mlx_engine_id(variant)
        registry = {"defaultEngineId": "mlx-audio@0.5.0", "defaultModelId": "large", "libraries": [],
                    "engines": [{"id": key, "repo": "mlx-audio", "commit": key.split("@")[1]} for key in ("mlx-audio@0.5.0", engine_id)],
                    "models": [{"id": "large", "repo": self.large["repo"], "revision": self.large["revision"], "activeVariantId": variant["id"], "installedVariants": [variant]}]}
        with patch.object(tts_registry, "read_tts_registry", return_value=registry), patch.object(
            tts_registry, "write_tts_registry"
        ), patch.object(tts_registry, "tts_registry_view", return_value={}), patch.object(
            tts_registry, "deps", SimpleNamespace(INFERENCE_SYNTHESIS_LOCK=threading.Lock(), active_export_job=lambda: None, shutdown_inference_worker=lambda: None)
        ):
            runtime = tts_registry.selected_tts_runtime()
            self.assertEqual(runtime["engine"]["id"], engine_id)
            self.assertEqual(runtime["engine"]["pythonPath"], "/large-python")
            self.assertEqual(runtime["model"]["precision"], "BF16")
            tts_registry.set_tts_active_variant("large", variant["id"])
            self.assertEqual(registry["defaultEngineId"], engine_id)
            self.assertEqual(len(registry["engines"]), 2)

    def test_install_verifies_auxiliary_terms_and_persists_large_runtime(self):
        for corrupt in (False, True):
            with self.subTest(corrupt_terms=corrupt), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / "models").mkdir()
                item = {**self.large, **self.variants[0], "baseModelId": self.large["id"], "variantId": "mlx-bf16"}
                digest = hashlib.sha256(b"verified").hexdigest()
                item["modelSha256"] = digest
                item["artifactFiles"] = [{"path": entry["path"], "sha256": digest} for entry in item["artifactFiles"]]
                registry = {"engines": [], "models": []}
                downloads = []

                def download(repo, revision, target, _state, _cancel, allowed):
                    downloads.append((repo, revision, allowed))
                    for name in allowed:
                        path = target / name
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b"corrupt" if corrupt and name == "NOTICE" else b"verified")

                with patch.object(tts_downloads, "deps", SimpleNamespace(
                    TTS_DOWNLOADS_ROOT=root / "downloads", TTS_MODELS_ROOT=root / "models", TTS_CODECS_ROOT=root / "codecs",
                    read_tts_registry=lambda: registry, write_tts_registry=lambda value: None,
                )), patch.object(tts_downloads, "_download_hf_repo", side_effect=download), patch.object(
                    tts_downloads, "_ensure_mlx_environment", return_value=root / "large-python"
                ):
                    if corrupt:
                        with self.assertRaisesRegex(ValueError, "NOTICE"):
                            tts_downloads._install_model(item, {}, threading.Event())
                        self.assertEqual(registry["models"], [])
                        self.assertFalse((root / "models" / item["revision"]).exists())
                    else:
                        tts_downloads._install_model(item, {}, threading.Event())
                        self.assertEqual(registry["defaultEngineId"], mlx_engine_id(item))
                        self.assertEqual(registry["models"][0]["installedVariants"][0]["runtimeEngineId"], mlx_engine_id(item))
                self.assertEqual(downloads[1], (item["auxiliaryAssets"]["repo"], item["auxiliaryAssets"]["revision"], item["auxiliaryAssets"]["downloadFiles"]))
                self.assertNotIn("NOTICE", downloads[0][2])

    def test_removing_last_large_mlx_variant_cleans_only_its_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            large_python = root / "env/large/bin/python"
            small_python = root / "env/small/bin/python"
            for path in (large_python, small_python):
                path.parent.mkdir(parents=True)
                path.touch()
            large_variant = {**self.variants[0], "path": str(root / "models/large")}
            engine_id = mlx_engine_id(large_variant)
            registry = {"engines": [{"id": engine_id, "pythonPath": str(large_python)}, {"id": "mlx-audio@0.5.0", "pythonPath": str(small_python)}],
                        "models": [{"id": "large", "activeVariantId": "pytorch-fp32", "installedVariants": [large_variant, {"id": "pytorch-fp32"}]},
                                   {"id": "small", "installedVariants": [{"id": "mlx-fp16", "backend": "mlx"}]}]}
            with patch.object(tts_registry, "read_tts_registry", return_value=copy.deepcopy(registry)), patch.object(
                tts_registry, "write_tts_registry"
            ) as write, patch.object(tts_registry, "tts_registry_view", return_value={}), patch.object(
                tts_registry, "remove_variant_files"
            ), patch.object(tts_registry, "deps", SimpleNamespace(TTS_ENVIRONMENTS_ROOT=root / "env", TTS_MODELS_ROOT=root / "models")):
                tts_registry.delete_tts_variant("large", "mlx-bf16")
            self.assertFalse(large_python.exists())
            self.assertTrue(small_python.is_file())
            self.assertEqual([e["id"] for e in write.call_args.args[0]["engines"]], ["mlx-audio@0.5.0"])

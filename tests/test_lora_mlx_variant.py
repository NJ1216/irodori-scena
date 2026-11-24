"""A local composition must never become an implicit fallback or own base files."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.modules.tts_mlx_fp32 import BASE_REPO, BASE_REVISION, add_local_fp32_variants
from server.modules.tts_registry import _active_variant


class LocalFp32Tests(unittest.TestCase):
    def test_composition_requires_both_assets_and_reuses_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, codec, python = root / "base", root / "mlx", root / "python"
            base.mkdir()
            codec.mkdir()
            python.touch()
            (base / "model.safetensors").touch()
            for name in ("config.json", "dacvae/model.safetensors", "dacvae/config.json", "tokenizer/tokenizer.json"):
                path = codec / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            variants = [{"id": "pytorch-fp32", "path": str(base)}, {"id": "mlx-fp16", "path": str(codec)}]
            model = {"repo": BASE_REPO, "revision": BASE_REVISION, "installedVariants": variants, "activeVariantId": "mlx-fp32"}
            registry = {"models": [model], "engines": [{"id": "mlx-audio@0.5.0", "pythonPath": str(python)}]}
            with patch("server.modules.tts_mlx_fp32.sys.platform", "darwin"), patch("server.modules.tts_mlx_fp32.platform.machine", return_value="arm64"):
                add_local_fp32_variants(registry)
                derived = _active_variant(model)
                self.assertEqual(derived["path"], str(base))
                self.assertEqual(derived["mlxAssetsPath"], str(codec))
                self.assertTrue(derived["derivedLocal"])
                self.assertEqual(derived["mlxAssetsRepo"], "mlx-community/Irodori-TTS-v4.1-Small-fp16")
                self.assertEqual(derived["mlxAssetsRevision"], "8be8d91091380115f1ac77aeb6604ed588d05372")
                (base / "model.safetensors").unlink()
                add_local_fp32_variants(registry)
                self.assertIsNone(_active_variant(model))
                self.assertEqual(model["activeVariantId"], "mlx-fp32")
                self.assertTrue((codec / "dacvae/model.safetensors").exists())

    def test_other_platform_removes_stale_composition(self):
        model = {"installedVariants": [{"id": "pytorch-fp32"}, {"id": "mlx-fp32"}], "activeVariantId": "mlx-fp32"}
        with patch("server.modules.tts_mlx_fp32.sys.platform", "win32"):
            add_local_fp32_variants({"models": [model], "engines": []})
        self.assertIsNone(_active_variant(model))

    def test_existing_pinned_hf_cache_can_supply_shared_base_without_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cached = root / "snapshot"
            cached.mkdir()
            (cached / "model.safetensors").touch()
            codec = root / "mlx"
            for name in ("config.json", "dacvae/model.safetensors", "dacvae/config.json", "tokenizer/tokenizer.json"):
                path = codec / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            python = root / "python"
            python.touch()
            model = {"repo": BASE_REPO, "revision": BASE_REVISION,
                     "installedVariants": [{"id": "mlx-fp16", "path": str(codec)}]}
            registry = {"models": [model], "engines": [{"id": "mlx-audio@0.5.0", "pythonPath": str(python)}]}
            with patch("server.modules.tts_mlx_fp32.sys.platform", "darwin"), patch("server.modules.tts_mlx_fp32.platform.machine", return_value="arm64"), patch("server.modules.tts_mlx_fp32.cached_base_path", return_value=cached):
                add_local_fp32_variants(registry)
                derived = next(item for item in model["installedVariants"] if item["id"] == "mlx-fp32")
                self.assertEqual(derived["path"], str(cached))
            with patch("server.modules.tts_mlx_fp32.sys.platform", "darwin"), patch("server.modules.tts_mlx_fp32.platform.machine", return_value="arm64"), patch("server.modules.tts_mlx_fp32.cached_base_path", return_value=None):
                add_local_fp32_variants(registry)
                self.assertFalse(any(item["id"] == "mlx-fp32" for item in model["installedVariants"]))

    def test_derived_delete_and_active_source_delete_never_touch_checkpoint(self):
        from server.modules import tts_registry
        from fastapi import HTTPException
        model = {"id": "fixture", "activeVariantId": "mlx-fp32", "installedVariants": [
            {"id": "pytorch-fp32"}, {"id": "mlx-fp16"}, {"id": "mlx-fp32", "derivedLocal": True}]}
        registry = {"models": [model]}
        with patch.object(tts_registry, "read_tts_registry", return_value=registry), patch.object(tts_registry, "remove_variant_files") as remove:
            for variant_id in ("mlx-fp32", "pytorch-fp32", "mlx-fp16"):
                with self.subTest(variant=variant_id), self.assertRaises(HTTPException) as caught:
                    tts_registry.delete_tts_variant("fixture", variant_id)
                self.assertEqual(caught.exception.status_code, 409)
            remove.assert_not_called()

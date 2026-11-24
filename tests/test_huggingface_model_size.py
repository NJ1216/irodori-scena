import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import huggingface_model_size as sizes, huggingface_metadata as metadata


def info(*files):
    return SimpleNamespace(sha="fixed", siblings=[SimpleNamespace(rfilename=name, size=size) for name, size in files])


class HuggingFaceModelSizeTests(unittest.TestCase):
    def test_gguf_uses_smallest_complete_known_variant_not_repository_sum(self):
        with patch.object(sizes.sys, "platform", "win32"):
            model = info(("model-Q4-00001-of-00002.gguf", 4), ("model-Q4-00002-of-00002.gguf", 4),
                         ("model-Q8.gguf", 16), ("incomplete-00001-of-00002.gguf", 1), ("unknown.gguf", None))
            self.assertEqual(sizes.model_download_size(model), 8)
            self.assertIsNone(sizes.model_download_size(info(("unknown.gguf", None))))
            self.assertIsNone(sizes.model_download_size(info()))

    def test_mlx_uses_downloaded_files_and_keeps_unknown_unknown(self):
        with patch.object(sizes.sys, "platform", "darwin"):
            self.assertEqual(sizes.model_download_size(info(("model.safetensors", 8), ("config.json", 1), ("onnx/model", 50))), 9)
            self.assertIsNone(sizes.model_download_size(info(("model.safetensors", None))))

    def test_legacy_repository_size_is_refetched_and_cached_by_revision_and_format(self):
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
                patch.object(sizes.sys, "platform", "win32"), patch.object(metadata, "HfApi") as api:
            metadata._write_cache({"org/model": {"revision": "fixed", "downloadSizeBytes": 100, "lastAccessedAt": 9999999999}})
            self.assertIsNone(metadata.cached_size("org/model", "fixed"))
            api.return_value.model_info.return_value = info(("model-Q4.gguf", 8), ("model-Q8.gguf", 16))
            self.assertEqual(metadata.fetch_metadata_sizes([{"repoId": "org/model", "revision": "fixed"}], lambda: None)["models"][0]["downloadSizeBytes"], 8)
            self.assertEqual(metadata.cached_size("org/model", "fixed"), 8)
            self.assertIsNone(metadata.cached_size("org/model", "new"))
            with patch.object(sizes.sys, "platform", "darwin"):
                self.assertIsNone(metadata.cached_size("org/model", "fixed"))

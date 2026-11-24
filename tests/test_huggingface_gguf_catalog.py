import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import huggingface_gguf as gguf, huggingface_models as models, huggingface_metadata as metadata


def info(*names):
    return SimpleNamespace(id="org/model-Q4", sha="fixed", tags=["gguf"], library_name=None, downloads=1, gated=False,
                           siblings=[SimpleNamespace(rfilename=name, size=10) for name in names])


class GgufCatalogTests(unittest.TestCase):
    def test_dynamic_quantizations_keep_their_full_identity(self):
        labels = ["Q4_K_M", "Q2_K_L", "UD-Q2_K_XL", "UD-Q3_K_XL", "UD-Q4_K_XL",
                  "UD-Q5_K_XL", "UD-Q6_K_XL", "UD-Q8_K_XL", "UD-IQ1_M", "UD-IQ2_XXS", "UD-TQ1_0"]
        result = gguf.variants_from_info("unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF",
            info(*(f"Qwen3-Coder-30B-A3B-Instruct-{label}.gguf" for label in labels)))
        self.assertEqual([item["quantization"] for item in result["variants"]], labels)
        self.assertIsNone(gguf.quantization_label("model-Q4_K_UNKNOWN.gguf"))

    def test_exact_quantizations_survive_prefixes_case_and_sharding(self):
        result = gguf.variants_from_info("org/model", info(
            "Q4_K_M/model.q4_k_m-00001-of-00002.gguf", "Q4_K_M/model.q4_k_m-00002-of-00002.gguf",
            "model_Q4_0.gguf", "model.IQ4_XS.gguf", "model-Q4.gguf", "model-BF16.gguf"))
        self.assertEqual([item["quantization"] for item in result["variants"]], ["Q4_K_M", "Q4_0", "IQ4_XS", "Q4", "BF16"])
        self.assertEqual(result["variants"][0]["downloadSizeBytes"], 20)

    def test_projection_and_invalid_shards_do_not_become_quantization_candidates(self):
        result = gguf.variants_from_info("org/model", info("mmproj-F16.gguf", "model-mmproj-Q8_0.gguf",
            "bad-Q4_K_M-00001-of-00002.gguf", "duplicate-Q5_K_M-00001-of-00002.gguf",
            "duplicate-Q5_K_M-00001-of-00002.gguf", "model-Q8_0.gguf"))
        self.assertEqual([item["quantization"] for item in result["variants"]], ["Q8_0"])

    def test_unknown_shard_size_does_not_become_a_small_known_variant(self):
        candidate = info("model-Q4_K_M-00001-of-00002.gguf", "model-Q4_K_M-00002-of-00002.gguf")
        candidate.siblings[1].size = None
        self.assertEqual(gguf.variants_from_info("org/model", candidate)["variants"][0]["downloadSizeBytes"], 0)

    def test_search_filters_on_file_catalog_not_repository_name(self):
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
                patch.object(models, "WINDOWS_MODEL_CATALOG", True), patch.object(models.sys, "platform", "win32"), patch.object(models, "HF_SEARCH_CACHE", {}), \
                patch.object(models, "HfApi") as api:
            api.return_value.list_models.return_value = [info("model-Q4_K_M.gguf", "model-Q8_0.gguf")]
            result = models.search_huggingface_models("model", ["quantization:Q4_K_M"])
            self.assertEqual(api.return_value.list_models.call_args.kwargs["search"], "model")
            self.assertEqual(len(result["models"]), 1)
            tags = result["models"][0]["inferredTags"]
            self.assertIn({"kind": "quantization", "value": "Q4_K_M"}, tags)
            self.assertNotIn({"kind": "quantization", "value": "Q4"}, tags)
            self.assertEqual(models.search_huggingface_models("model", ["quantization:Q4"])["models"], [])

    def test_catalog_is_persisted_by_revision_and_reused_by_search(self):
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
                patch.object(models, "WINDOWS_MODEL_CATALOG", True), patch.object(models.sys, "platform", "win32"), patch.object(metadata, "HfApi") as api, \
                patch.object(models, "HF_SEARCH_CACHE", {}):
            api.return_value.model_info.return_value = info("model-Q4_K_M.gguf", "model-Q4_0.gguf")
            request = [{"repoId": "org/model-Q4", "revision": "fixed"}]
            first = metadata.fetch_metadata_sizes(request, lambda: None)
            self.assertEqual(metadata.fetch_metadata_sizes(request, lambda: None), first)
            self.assertEqual(api.return_value.model_info.call_count, 1)
            self.assertIsNone(metadata.cached_gguf_catalog("org/model-Q4", "new"))
            self.assertEqual([item["quantization"] for item in metadata.cached_gguf_catalog("org/model-Q4", "fixed")], ["Q4_K_M", "Q4_0"])
            candidate = info()
            candidate.siblings = None
            with patch.object(models, "HfApi") as search:
                search.return_value.list_models.return_value = [candidate]
                result = models.search_huggingface_models("model", ["quantization:Q4_K_M"])
            self.assertEqual(len(result["models"]), 1)

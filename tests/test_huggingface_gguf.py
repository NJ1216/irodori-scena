from __future__ import annotations

import scena_test_isolation  # noqa: F401
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import huggingface_gguf, huggingface_models


def sibling(name: str, size: int) -> SimpleNamespace:
    return SimpleNamespace(rfilename=name, size=size)


class HuggingFaceGgufTests(unittest.TestCase):
    def test_groups_variants_and_excludes_incomplete_shards(self):
        info = SimpleNamespace(sha="fixed", siblings=[
            sibling("model-Q4_K_M-00001-of-00002.gguf", 10), sibling("model-Q4_K_M-00002-of-00002.gguf", 20),
            sibling("model-Q8_0.gguf", 40), sibling("broken-00001-of-00002.gguf", 5),
        ])
        result = huggingface_gguf.variants_from_info("org/model", info)
        self.assertEqual(result["revision"], "fixed")
        self.assertEqual([(item["id"], item["shardCount"], item["downloadSizeBytes"]) for item in result["variants"]], [
            ("model-Q4_K_M", 2, 30), ("model-Q8_0", 1, 40),
        ])

    def test_download_uses_only_selected_variant_at_the_resolved_revision(self):
        info = SimpleNamespace(id="org/model", sha="fixed", tags=["gguf"], library_name="transformers", siblings=[
            sibling("model-Q4.gguf", 10), sibling("model-Q8.gguf", 20), sibling("README.md", 30),
        ])
        state = {"state": "queued", "downloadedBytes": 0, "totalBytes": 0}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(huggingface_models, "WINDOWS_MODEL_CATALOG", True), patch.object(huggingface_models.sys, "platform", "win32"), \
                patch("server.modules.constants.LOCAL_LLM_ROOT", Path(directory)), \
                patch.object(huggingface_models, "_model_info_with_optional_token", return_value=(info, None)), \
                patch.object(huggingface_models, "_download_file") as download, \
                patch("server.modules.llm_registry.register_local_llm_card", return_value={"id": "card"}):
            huggingface_models._download_repo("org/model", state, threading.Event(), "model-Q4")
        self.assertEqual(download.call_count, 1)
        self.assertEqual(download.call_args.args[1:3], ("model-Q4.gguf", "fixed"))
        self.assertEqual(state["state"], "complete")

    def test_windows_model_download_starts_automatic_runtime_preparation(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("server.modules.llama_cpp_runtime.selected_backend", return_value="cpu"), \
                patch("server.modules.llm_registry.read_llm_registry", return_value={"cards": []}), \
                patch.object(huggingface_models, "WINDOWS_MODEL_CATALOG", True), patch.object(huggingface_models.sys, "platform", "win32"), \
                patch("server.modules.constants.LOCAL_LLM_ROOT", Path(directory)), \
                patch("server.modules.llm_registry.register_local_llm_card", return_value={"id": "card"}), \
                patch("server.modules.model_runtime_jobs.start_model_runtime") as prepare, \
                patch.object(huggingface_models.threading.Thread, "start"):
            huggingface_models.start_huggingface_download("org/model", "model-Q4")

        prepare.assert_called_once_with("card", automatic=True)

from __future__ import annotations

import tempfile
import io
import json
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from fastapi import HTTPException

from server.modules import huggingface_metadata, huggingface_models, huggingface_preparation


class HuggingFaceModelsTests(unittest.TestCase):
    def setUp(self) -> None:
        huggingface_models.HF_SEARCH_CACHE.clear()
        self.catalog_platform = patch.object(huggingface_models, "WINDOWS_MODEL_CATALOG", False)
        self.addition_platform = patch.object(huggingface_preparation, "WINDOWS_MODEL_ADDITION", False)
        self.catalog_platform.start()
        self.addition_platform.start()
        self.addCleanup(self.catalog_platform.stop)
        self.addCleanup(self.addition_platform.stop)

    def test_keychain_read_failure_does_not_block_public_search(self) -> None:
        with patch.object(huggingface_models.keyring, "get_password", side_effect=RuntimeError("locked")):
            self.assertIsNone(huggingface_models._token())

    def test_search_filters_clearly_incompatible_results(self) -> None:
        models = [
            SimpleNamespace(id="mlx-community/good-4bit", tags=["mlx"], library_name="mlx", downloads=3, gated=False),
            SimpleNamespace(id="someone/gguf", tags=["gguf"], library_name="transformers", downloads=2, gated=False),
            SimpleNamespace(id="someone/unknown", tags=[], library_name=None, downloads=1, gated=False),
        ]
        def list_models(*, search: str | None, filter: str | None, sort: str, limit: int, full: bool) -> object:
            self.assertEqual((search, filter, sort, limit, full), ("model", "mlx", "downloads", 30, True))
            return iter(models)
        with patch.object(huggingface_models, "HfApi") as api, patch.object(huggingface_models, "_token", return_value=None):
            api.return_value.list_models.side_effect = list_models
            result = huggingface_models.search_huggingface_models("model")
        self.assertEqual([item["repoId"] for item in result["models"]], ["mlx-community/good-4bit"])
        self.assertEqual(result["models"][0]["publisher"], "mlx-community")
        self.assertIn({"kind": "compatibility", "value": "MLX"}, result["models"][0]["inferredTags"])
        self.assertTrue(result["mlxOnly"])

    def test_search_marks_only_the_pinned_mtp_target(self) -> None:
        models = [
            SimpleNamespace(id=huggingface_models.MTP_TARGET_REPO, sha=huggingface_models.MTP_TARGET_REVISION,
                            tags=["mlx"], library_name="mlx", downloads=2, gated=False),
            SimpleNamespace(id="mlx-community/gemma-4-31b-it-4bit", sha="other",
                            tags=["mlx"], library_name="mlx", downloads=1, gated=False),
        ]
        with patch.object(huggingface_models, "HfApi") as api:
            api.return_value.list_models.return_value = iter(models)
            result = huggingface_models.search_huggingface_models("gemma")
        mtp_tag = {"kind": "compatibility", "value": "MTP対応"}
        self.assertIn(mtp_tag, result["models"][0]["inferredTags"])
        self.assertNotIn(mtp_tag, result["models"][1]["inferredTags"])

    def test_selected_tags_create_a_new_search_and_are_and_matched(self) -> None:
        models = [
            SimpleNamespace(id="org/gemma-4-test-4b-nvfp4", sha="one", tags=["mlx"],
                            library_name="mlx", downloads=2, gated=False),
            SimpleNamespace(id="org/gemma-4-test-12b-nvfp4", sha="two", tags=["mlx"],
                            library_name="mlx", downloads=1, gated=False),
        ]
        with patch.object(huggingface_models, "HfApi") as api:
            api.return_value.list_models.return_value = iter(models)
            result = huggingface_models.search_huggingface_models(
                "gemma", ["family:Gemma 4", "parameters:4B", "quantization:NVFP4"])
        self.assertEqual(api.return_value.list_models.call_args.kwargs["search"], "gemma Gemma 4 4B NVFP4")
        self.assertEqual([item["repoId"] for item in result["models"]],
                         ["org/gemma-4-test-4b-nvfp4"])

    def test_search_cache_reuses_the_same_normalized_conditions(self) -> None:
        model = SimpleNamespace(id="org/gemma-4-4b", sha="one", tags=["mlx"],
                                library_name="mlx", downloads=1, gated=False)
        with patch.object(huggingface_models, "HfApi") as api:
            api.return_value.list_models.return_value = iter([model])
            first = huggingface_models.search_huggingface_models("gemma", ["parameters:4B"])
            second = huggingface_models.search_huggingface_models(" GEMMA ", ["parameters:4B"])
        self.assertEqual(first, second)
        api.return_value.list_models.assert_called_once()

    def test_repository_name_tags_are_deterministic_and_conservative(self) -> None:
        self.assertEqual(huggingface_models._inferred_tags("gpt-oss-120b-MXFP4"), [
            {"kind": "family", "value": "gpt-oss"},
            {"kind": "parameters", "value": "120B"},
            {"kind": "quantization", "value": "MXFP4"},
        ])
        self.assertEqual(huggingface_models._inferred_tags("Qwen2.5-0.5b-Instruct-4bit"), [
            {"kind": "family", "value": "Qwen 2.5"},
            {"kind": "parameters", "value": "0.5B"},
            {"kind": "quantization", "value": "4bit"},
            {"kind": "purpose", "value": "Instruct"},
        ])
        self.assertEqual(huggingface_models._inferred_tags("model-small-instruct"), [
            {"kind": "purpose", "value": "Instruct"},
        ])

    def test_family_normalization_separates_generation_and_derivatives(self) -> None:
        families = [huggingface_models._inferred_tags(value)[0]["value"] for value in
                    ("Gemma-3", "gemma 3", "GEMMA_3")]
        self.assertEqual(families, ["Gemma 3"] * 3)
        self.assertEqual([huggingface_models._inferred_tags(value)[0]["value"] for value in
                          ("Gemma-3", "Gemma-4", "Gemma-3.5")], ["Gemma 3", "Gemma 4", "Gemma 3.5"])
        self.assertEqual(huggingface_models._inferred_tags("deepseek-r1-7b")[0]["value"], "DeepSeek R1")
        self.assertEqual(huggingface_models._inferred_tags("Gemma-3-4B-it-qat-4bit"), [
            {"kind": "family", "value": "Gemma 3"}, {"kind": "parameters", "value": "4B"},
            {"kind": "quantization", "value": "QAT"}, {"kind": "quantization", "value": "4bit"},
            {"kind": "purpose", "value": "Instruct"},
        ])
        self.assertEqual(huggingface_models._inferred_tags("Qwen-2.5-Coder-7B-Instruct"), [
            {"kind": "family", "value": "Qwen 2.5"}, {"kind": "parameters", "value": "7B"},
            {"kind": "purpose", "value": "Coder"}, {"kind": "purpose", "value": "Instruct"},
        ])
        self.assertEqual(huggingface_models._inferred_tags("gemma-4-31B-it-MLX-6bit"), [
            {"kind": "family", "value": "Gemma 4"}, {"kind": "parameters", "value": "31B"},
            {"kind": "quantization", "value": "6bit"}, {"kind": "purpose", "value": "Instruct"},
            {"kind": "compatibility", "value": "MLX"},
        ])
        self.assertEqual(huggingface_models._inferred_tags("gemma-4-26B-A4B-it-QAT-MLX-4bit"), [
            {"kind": "family", "value": "Gemma 4"}, {"kind": "parameters", "value": "26B"},
            {"kind": "quantization", "value": "QAT"}, {"kind": "quantization", "value": "4bit"},
            {"kind": "purpose", "value": "Instruct"}, {"kind": "compatibility", "value": "MLX"},
        ])

    def test_search_facets_normalize_real_world_gemma_names(self) -> None:
        self.assertEqual(huggingface_models._inferred_tags(
            "AX-Gemma-4-12B-IT-MLX-QAT-OptiQ-4bit-Assistant-MTP"), [
                {"kind": "family", "value": "Gemma 4"}, {"kind": "parameters", "value": "12B"},
                {"kind": "quantization", "value": "QAT"}, {"kind": "quantization", "value": "OptiQ"},
                {"kind": "quantization", "value": "4bit"}, {"kind": "purpose", "value": "Instruct"},
                {"kind": "role", "value": "Assistant"}, {"kind": "compatibility", "value": "MLX"},
            ])
        self.assertEqual(huggingface_models._inferred_tags("gemma-4-26B-A4B-it-oQ3.5e-mtp"), [
            {"kind": "family", "value": "Gemma 4"}, {"kind": "parameters", "value": "26B"},
            {"kind": "quantization", "value": "oQ3.5e"}, {"kind": "purpose", "value": "Instruct"},
        ])
        self.assertEqual(huggingface_models._inferred_tags(
            "ravenx-Gemma4-12B-MTP-OBLITERATED-OpenMAI-OpenMythos-deep-reasoning-mlx"), [
                {"kind": "family", "value": "Gemma 4"}, {"kind": "parameters", "value": "12B"},
                {"kind": "purpose", "value": "Thinking"}, {"kind": "compatibility", "value": "MLX"},
            ])
        self.assertEqual(huggingface_models._inferred_tags("gemma-4-E2B-it-qat-assistant-4bit"), [
            {"kind": "family", "value": "Gemma 4"}, {"kind": "parameters", "value": "E2B"},
            {"kind": "quantization", "value": "QAT"}, {"kind": "quantization", "value": "4bit"},
            {"kind": "purpose", "value": "Instruct"}, {"kind": "role", "value": "Assistant"},
        ])

    def test_search_facets_normalize_real_world_gpt_oss_names(self) -> None:
        self.assertEqual(huggingface_models._inferred_tags("AX-gpt-oss-20b-axq-6bit"), [
            {"kind": "family", "value": "gpt-oss"}, {"kind": "parameters", "value": "20B"},
            {"kind": "quantization", "value": "AXQ"}, {"kind": "quantization", "value": "6bit"},
        ])
        self.assertEqual(huggingface_models._inferred_tags(
            "OpenAI-gpt-oss-20B-INSTRUCT-Heretic-Uncensored-MXFP4-Q4-8bit"), [
                {"kind": "family", "value": "gpt-oss"}, {"kind": "parameters", "value": "20B"},
                {"kind": "quantization", "value": "MXFP4"}, {"kind": "quantization", "value": "Q4"},
                {"kind": "quantization", "value": "8bit"}, {"kind": "purpose", "value": "Instruct"},
            ])
        self.assertEqual(huggingface_models._inferred_tags("gpt-oss-safeguard-120b-MLX-MXFP4"), [
            {"kind": "family", "value": "gpt-oss"}, {"kind": "parameters", "value": "120B"},
            {"kind": "quantization", "value": "MXFP4"}, {"kind": "purpose", "value": "Safety"},
            {"kind": "compatibility", "value": "MLX"},
        ])

    def test_metadata_cache_uses_revision_and_recovers_from_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
                patch.object(huggingface_metadata, "HfApi") as api:
            cache = Path(directory) / "huggingface-model-metadata-cache.json"
            cache.write_text("broken", encoding="utf-8")
            api.return_value.model_info.return_value = SimpleNamespace(sha="fixed", siblings=[SimpleNamespace(rfilename="model.gguf", size=6800)])
            first = huggingface_metadata.fetch_metadata_sizes([{"repoId": "org/model", "revision": "one"}], lambda: None)
            second = huggingface_metadata.fetch_metadata_sizes([{"repoId": "org/model", "revision": "one"}], lambda: None)
            third = huggingface_metadata.fetch_metadata_sizes([{"repoId": "org/model", "revision": "two"}], lambda: None)
            self.assertEqual(first["models"][0]["downloadSizeBytes"], 6800)
            self.assertEqual(second, first)
            self.assertEqual(api.return_value.model_info.call_count, 2)
            self.assertEqual(json.loads(cache.read_text())["repositories"]["org/model"]["revision"], "two")
            self.assertEqual(third["models"][0]["downloadSizeBytes"], 6800)

    def test_metadata_partial_failure_returns_null_without_failing_siblings(self) -> None:
        def model_info(repo: str, **_options: object) -> object:
            if repo == "org/bad":
                raise HfHubHTTPError("unavailable", response=Mock(headers={}))
            return SimpleNamespace(sha="fixed", siblings=[SimpleNamespace(rfilename="model.gguf", size=42)])
        from huggingface_hub.errors import HfHubHTTPError
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.DATA_ROOT", Path(directory)), \
                patch.object(huggingface_metadata, "HfApi") as api:
            api.return_value.model_info.side_effect = model_info
            result = huggingface_metadata.fetch_metadata_sizes([
                {"repoId": "org/good", "revision": "one"}, {"repoId": "org/bad", "revision": "one"}], lambda: None)
        self.assertEqual([{key: item[key] for key in ("repoId", "downloadSizeBytes")} for item in result["models"]], [
            {"repoId": "org/good", "downloadSizeBytes": 42}, {"repoId": "org/bad", "downloadSizeBytes": None}])

    def test_search_size_uses_repository_storage_and_stays_anonymous(self) -> None:
        model = SimpleNamespace(id="mlx-community/model-1T-BF16", tags=["mlx"], library_name="mlx",
                                downloads=1, gated=False, sha="revision", used_storage=1234)
        with patch.object(huggingface_models, "HfApi") as api:
            api.return_value.list_models.return_value = iter([model])
            result = huggingface_models.search_huggingface_models("model")
        api.assert_called_once_with(token=False)
        self.assertIsNone(result["models"][0]["downloadSizeBytes"])
        self.assertEqual(result["models"][0]["revision"], "revision")
        self.assertIn({"kind": "parameters", "value": "1T"}, result["models"][0]["inferredTags"])

    def test_repo_id_rejects_path_traversal(self) -> None:
        with self.assertRaises(HTTPException):
            huggingface_models.start_huggingface_download("../model")

    def test_download_uses_fixed_managed_root_and_can_resume_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "local-llm"
            info = SimpleNamespace(sha="revision", tags=["mlx"], library_name="mlx", id="org/model",
                                   siblings=[SimpleNamespace(rfilename="config.json", size=2), SimpleNamespace(rfilename="weights.safetensors", size=3)])
            state = {"state": "queued", "downloadedBytes": 0, "totalBytes": 0}
            class Response(io.BytesIO):
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args: object) -> None:
                    self.close()
            with (
                patch("server.modules.constants.LOCAL_LLM_ROOT", root),
                patch.object(huggingface_models, "HfApi") as api,
                patch.object(huggingface_models.urllib.request, "urlopen", side_effect=lambda *_args, **_kwargs: Response(b"abc")),
                patch("server.modules.local_llm_storage.rebuild_local_llm_discovery"),
                patch("server.modules.llm_registry.register_local_llm_card", return_value={"id": "card"}),
                patch.object(huggingface_models, "_token", return_value=None),
            ):
                api.return_value.model_info.return_value = info
                huggingface_models._download_repo("org/model", state, __import__("threading").Event())
            api.return_value.model_info.assert_called_once_with("org/model", token=False, revision=None, files_metadata=True)
            self.assertEqual(state["state"], "complete")
            self.assertTrue((root / "models" / "org--model" / "weights.safetensors").is_file())

    def test_download_reports_each_chunk_and_stops_inside_a_large_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            cancel = threading.Event()
            state = {"downloadedBytes": 0}

            class Response:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args: object) -> None:
                    pass

                def read(self, _size: int) -> bytes:
                    if state["downloadedBytes"]:
                        cancel.set()
                    return b"first chunk"

            with patch.object(huggingface_models.urllib.request, "urlopen", return_value=Response()):
                with self.assertRaises(InterruptedError):
                    huggingface_models._download_file("org/model", "weights.safetensors", "rev", target, state, cancel)
            self.assertGreater(state["downloadedBytes"], 0)
            self.assertTrue((target / "weights.safetensors.part").is_file())

    def test_chunk_progress_is_incremental_without_directory_rescan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = {"downloadedBytes": 7}
            class Response(io.BytesIO):
                status = 200
                def __enter__(self): return self
                def __exit__(self, *_args: object) -> None: self.close()
            with patch.object(huggingface_models.urllib.request, "urlopen", return_value=Response(b"abc")):
                huggingface_models._download_file("org/model", "file", "rev", Path(directory), state, threading.Event())
            self.assertEqual(state["downloadedBytes"], 10)

    def test_large_file_uses_parallel_byte_ranges(self) -> None:
        payload = b"abcdefghijklmnopqrstuvwxyz"
        ranges: list[str] = []
        class Response(io.BytesIO):
            status = 206
            def __enter__(self): return self
            def __exit__(self, *_args: object) -> None: self.close()
        def respond(request: object, **_options: object) -> Response:
            header = request.get_header("Range")
            ranges.append(header)
            start, end = (int(value) for value in header.removeprefix("bytes=").split("-"))
            return Response(payload[start:end + 1])
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(huggingface_models, "MIN_PARALLEL_FILE_BYTES", 4), \
                patch.object(huggingface_models, "DOWNLOAD_PARALLELISM", 4), \
                patch.object(huggingface_models.urllib.request, "urlopen", side_effect=respond):
            state = {"downloadedBytes": 0, "currentFile": None}
            target = Path(directory)
            huggingface_models._download_file("org/model", "weights", "rev", target, state, threading.Event(), file_size=len(payload))
            self.assertEqual((target / "weights").read_bytes(), payload)
            self.assertEqual(state["downloadedBytes"], len(payload))
            self.assertGreater(len(ranges), 2)
            self.assertFalse((target / "weights.part.json").exists())

    def test_startup_cleanup_only_removes_expired_partial_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.LOCAL_LLM_ROOT", Path(directory)):
            root = Path(directory) / "models" / "org--model"
            root.mkdir(parents=True)
            stale = root / "old.part"
            stale_manifest = root / "old.part.json"
            recent = root / "recent.part"
            model = root / "weights.safetensors"
            for path in (stale, stale_manifest, recent, model):
                path.write_bytes(b"x")
            old = time.time() - huggingface_models.PARTIAL_CACHE_MAX_AGE_SECONDS - 1
            os.utime(stale, (old, old))
            os.utime(stale_manifest, (old, old))
            self.assertEqual(huggingface_models.cleanup_stale_huggingface_partials(), 2)
            self.assertFalse(stale.exists())
            self.assertFalse(stale_manifest.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(model.exists())

    def test_cancel_immediately_exposes_cancelling_state(self) -> None:
        job_id = "hf_cancel_test"
        huggingface_models.HF_DOWNLOADS[job_id] = {"id": job_id, "state": "downloading"}
        huggingface_models.HF_CANCEL[job_id] = threading.Event()
        try:
            result = huggingface_models.cancel_huggingface_download(job_id)
            self.assertEqual(result["state"], "cancelling")
            self.assertTrue(huggingface_models.HF_CANCEL[job_id].is_set())
        finally:
            huggingface_models.HF_DOWNLOADS.pop(job_id, None)
            huggingface_models.HF_CANCEL.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()

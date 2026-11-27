from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import copy
import tempfile
import hashlib
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import keyring

from fastapi.testclient import TestClient

import server.app as app_module
from server.modules import constants
from server.modules import inference as inference_module
from server.modules import runtime_state
from server.modules import tts_registry as tts_registry_module
from server.modules import tts_disk_usage


class TtsRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.patches = [
            # Registry fixtures use dummy assets/Popen; a preparation thread
            # must never outlive those patches and consume a sibling's mock.
            patch("server.modules.tts_runtime.start_tts_prepare", return_value={}),
            patch.dict(os.environ, {"HF_HOME": str(self.root / "empty-huggingface")}),
            patch.object(keyring, "get_password", return_value=None),
            patch.object(constants, "DATA_ROOT", self.root),
            patch.object(constants, "APP_STATE_FILE", self.root / "app-state.json"),
            patch.object(constants, "TTS_ASSETS_ROOT", self.root / "tts"),
            patch.object(constants, "TTS_ENGINES_ROOT", self.root / "tts/engines"),
            patch.object(constants, "TTS_ENVIRONMENTS_ROOT", self.root / "tts/environments"),
            patch.object(constants, "TTS_MODELS_ROOT", self.root / "tts/models"),
            patch.object(constants, "TTS_CODECS_ROOT", self.root / "tts/codecs"),
            patch.object(constants, "TTS_DOWNLOADS_ROOT", self.root / "tts/downloads"),
            patch.object(constants, "TTS_REGISTRY_FILE", self.root / "tts/registry.json"),
            patch.object(constants, "PROJECT_FILE", self.root / "project.json"),
            patch.object(constants, "MEDIA_ROOT", self.root / "media"),
            patch.object(constants, "ACTIVE_PROJECT_ROOT", self.root),
            patch.object(constants, "ACTIVE_PROJECT_PATH", None),
            patch.object(constants, "CONNECTION_SETTINGS_FILE", self.root / "connection-settings.json"),
        ]
        for item in self.patches:
            item.start()
        app_module.ensure_data_root()
        app_module.ensure_tts_storage()
        self.client = TestClient(app_module.app)

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temporary.cleanup()

    def _external_library_fixture(self) -> tuple[Path, Path, Path, Path]:
        root = self.root / "existing-library"
        engine = root / "checkout"
        model = root / "nested/models/standard"
        codec = root / "shared/codec"
        (engine / "irodori_tts").mkdir(parents=True)
        (engine / ".venv/bin").mkdir(parents=True)
        (model / "tokenizer").mkdir(parents=True)
        codec.mkdir(parents=True)
        (engine / "infer.py").write_text("", encoding="utf-8")
        python = engine / ".venv/bin/python"
        python.write_text("#!/bin/sh\n", encoding="utf-8")
        python.chmod(0o755)
        (model / "model.safetensors").write_bytes(b"known-model")
        (codec / "weights.pth").write_bytes(b"known-codec")
        return root, engine, model, codec

    def test_external_library_scan_register_verify_and_disconnect_is_non_destructive(self) -> None:
        root, engine, model, codec = self._external_library_fixture()
        ignored = root / "ignored-link"
        ignored.symlink_to(model, target_is_directory=True)
        scan = self.client.post("/api/tts/libraries/scan", json={"path": str(root)}).json()
        self.assertEqual([item["path"] for item in scan["engines"]], [str(engine.resolve())])
        self.assertEqual([item["path"] for item in scan["models"]], [str(model.resolve())])
        self.assertEqual([item["path"] for item in scan["codecs"]], [str(codec.resolve())])

        registry = self.client.post("/api/tts/libraries", json={"root": str(root), "engine_path": str(engine)}).json()
        library_id = registry["libraries"][0]["id"]
        catalog = app_module.tts_catalog()
        catalog["models"][0]["modelSha256"] = hashlib.sha256(b"known-model").hexdigest()
        catalog["models"][0]["codecSha256"] = hashlib.sha256(b"known-codec").hexdigest()
        with patch.object(tts_registry_module, "tts_catalog", return_value=catalog):
            job = self.client.post(f"/api/tts/libraries/{library_id}/models", json={"model_path": str(model), "codec_path": str(codec)}).json()
            for _ in range(100):
                job = self.client.get(f"/api/tts/library-model-jobs/{job['id']}").json()
                if job["state"] not in {"queued", "running", "cancelling"}:
                    break
                time.sleep(0.01)
        self.assertEqual(job["state"], "complete")
        registry = self.client.get("/api/tts/registry").json()
        self.assertEqual(registry["version"], 3)
        self.assertEqual(registry["models"][0]["libraryId"], library_id)
        self.assertEqual(registry["models"][0]["description"], "音声品質を重視した標準モデルです。どれを選ぶか迷った場合におすすめです。")
        self.assertEqual(registry["models"][0]["diskBytes"], len(b"known-model") + len(b"known-codec"))
        self.assertIn("diskUsageFingerprint", app_module.read_tts_registry()["models"][0])
        (model / "model.safetensors").write_bytes(b"known-model-with-new-size")
        refreshed = self.client.get("/api/tts/registry").json()["models"][0]
        self.assertEqual(refreshed["diskBytes"], len(b"known-model-with-new-size") + len(b"known-codec"))
        replacement = root / "replacement/standard"
        (replacement / "tokenizer").mkdir(parents=True)
        (replacement / "model.safetensors").write_bytes(b"known-model")
        with patch.object(tts_registry_module, "tts_catalog", return_value=catalog):
            relink = self.client.post(f"/api/tts/libraries/{library_id}/models", json={"model_path": str(replacement), "codec_path": str(codec)}).json()
            for _ in range(100):
                relink = self.client.get(f"/api/tts/library-model-jobs/{relink['id']}").json()
                if relink["state"] not in {"queued", "running", "cancelling"}:
                    break
                time.sleep(0.01)
        self.assertEqual(relink["state"], "complete")
        self.assertTrue(relink["duplicate"])
        relinked = self.client.get("/api/tts/registry").json()["models"][0]
        self.assertEqual(Path(relinked["path"]).resolve(), replacement.resolve())
        self.assertEqual(relinked["diskBytes"], len(b"known-model") + len(b"known-codec"))
        self.assertEqual(self.client.delete(f"/api/tts/libraries/{library_id}").status_code, 409)
        self.client.delete(f"/api/tts/model/{registry['models'][0]['id']}").raise_for_status()
        self.client.delete(f"/api/tts/libraries/{library_id}").raise_for_status()
        self.assertTrue((model / "model.safetensors").is_file())
        self.assertTrue((codec / "weights.pth").is_file())
        self.assertTrue((engine / "infer.py").is_file())

    def test_version_one_registry_migrates_with_empty_libraries(self) -> None:
        app_module.write_tts_registry({"version": 1, "engines": [], "models": [], "defaultEngineId": None, "defaultModelId": None})
        registry = app_module.read_tts_registry()
        self.assertEqual(registry["version"], 3)
        self.assertEqual(registry["models"], [])
        self.assertEqual(registry["libraries"], [])

    def test_external_usage_follows_file_links_deduplicates_and_keeps_last_value_offline(self) -> None:
        blobs = self.root / "blobs"
        blobs.mkdir()
        shared = blobs / "shared"
        shared.write_bytes(b"shared-asset")
        model = self.root / "snapshot-model"
        codec = self.root / "snapshot-codec"
        tokenizer = self.root / "snapshot-tokenizer"
        for directory in (model, codec, tokenizer):
            directory.mkdir()
        (model / "model.safetensors").symlink_to(shared)
        (codec / "weights.pth").symlink_to(shared)
        (tokenizer / "tokenizer.json").symlink_to(shared)
        card = {"source": "external", "libraryId": "library:test", "path": str(model),
                "codecPath": str(codec), "tokenizerPath": str(tokenizer), "diskBytes": None}

        self.assertTrue(tts_registry_module.refresh_external_model_disk_usage(card))
        self.assertEqual(card["diskBytes"], len(b"shared-asset"))
        previous = copy.deepcopy(card["diskUsageFingerprint"])
        (model / "model.safetensors").unlink()
        self.assertFalse(tts_registry_module.refresh_external_model_disk_usage(card))
        self.assertEqual(card["diskBytes"], len(b"shared-asset"))
        self.assertEqual(card["diskUsageFingerprint"], previous)

    def test_external_usage_skips_asset_walk_when_quick_signature_is_unchanged(self) -> None:
        model = self.root / "model"
        codec = self.root / "codec"
        tokenizer = self.root / "tokenizer"
        for directory in (model, codec, tokenizer):
            directory.mkdir()
        (model / "model.safetensors").write_bytes(b"model")
        (codec / "weights.pth").write_bytes(b"codec")
        (tokenizer / "tokenizer.json").write_bytes(b"tokenizer")
        card = {"source": "external", "libraryId": "library:test", "path": str(model),
                "codecPath": str(codec), "tokenizerPath": str(tokenizer), "diskBytes": None}

        with patch.object(tts_disk_usage, "_asset_usage", wraps=tts_disk_usage._asset_usage) as usage:
            self.assertTrue(tts_registry_module.refresh_external_model_disk_usage(card))
            self.assertFalse(tts_registry_module.refresh_external_model_disk_usage(card))
        self.assertEqual(usage.call_count, 1)

    def test_legacy_project_selection_never_overrides_global_selection(self) -> None:
        catalog = app_module.tts_catalog()
        engine, global_model, project_model = catalog["engines"][0], catalog["models"][0], catalog["models"][4]
        registry = {"version": 2, "defaultEngineId": engine["id"], "defaultModelId": global_model["id"],
                    "engines": [{"id": engine["id"], "repo": engine["repo"], "commit": engine["commit"]}],
                    "models": [{"id": item["id"], "repo": item["repo"], "revision": item["revision"],
                                "codecRevision": item["codecRevision"]} for item in (global_model, project_model)], "libraries": []}
        app_module.write_tts_registry(registry)
        project = app_module.read_project()
        project.pop("ttsSelection", None)
        app_module.write_project(project)
        self.assertEqual(self.client.get("/api/tts/registry").json()["activeModelId"], global_model["id"])
        project["ttsSelection"] = {"engine": {"repo": engine["repo"], "commit": engine["commit"]},
                                   "model": {"repo": project_model["repo"], "revision": project_model["revision"]}}
        app_module.write_project(project)
        view = self.client.get("/api/tts/registry").json()
        self.assertEqual(view["activeModelId"], global_model["id"])
        self.assertEqual(view["defaultModelId"], global_model["id"])

    def test_model_selection_changes_global_registry_without_persisting_in_project(self) -> None:
        catalog = app_module.tts_catalog()
        engine, global_model, selected_model = catalog["engines"][0], catalog["models"][4], catalog["models"][0]
        app_module.write_tts_registry({
            "version": 2, "defaultEngineId": engine["id"], "defaultModelId": global_model["id"],
            "engines": [{"id": engine["id"], "source": "managed", "repo": engine["repo"], "commit": engine["commit"]}],
            "models": [{"id": item["id"], "source": "managed", "repo": item["repo"], "revision": item["revision"],
                        "codecRevision": item["codecRevision"]} for item in (global_model, selected_model)], "libraries": [],
        })
        project = app_module.read_project()
        project["characters"] = json.loads((Path(__file__).parent / "fixtures/project-contract.json").read_text())["characters"]
        project["scenes"][0]["lines"] = [{"id": "line-1", "characterId": project["characters"][0]["id"], "text": "保持", "takes": [{
            "id": "take-1", "audioUrl": "/media/existing.wav", "selected": True, "seed": 1,
            "quality": "fast", "createdAt": 1,
            "ttsConfiguration": {"engineCommit": "old-engine", "modelRevision": "old-model",
                                 "codecRevision": "old-codec", "optimizationProfile": "old-profile"},
        }]}]
        app_module.write_project(project)
        saved_root = self.root / "saved.scena"
        saved_root.mkdir()
        with patch.object(constants, "ACTIVE_PROJECT_ROOT", saved_root), patch.object(inference_module, "shutdown_inference_worker") as stop:
            response = self.client.put("/api/project/tts-selection", json={
                "model_id": selected_model["id"],
            })
        self.assertEqual(response.status_code, 200)
        stored = json.loads(constants.PROJECT_FILE.read_text(encoding="utf-8"))
        self.assertNotIn("ttsSelection", stored)
        self.assertEqual(app_module.read_tts_registry()["defaultModelId"], selected_model["id"])
        self.assertEqual(stored["scenes"][0]["lines"][0]["takes"][0], project["scenes"][0]["lines"][0]["takes"][0])
        stop.assert_called_once()

    def test_scratch_default_change_does_not_write_project_selection(self) -> None:
        catalog = app_module.tts_catalog()
        engine, model = catalog["engines"][0], catalog["models"][0]
        app_module.write_tts_registry({
            "version": 2, "defaultEngineId": engine["id"], "defaultModelId": None,
            "engines": [{"id": engine["id"], "source": "managed", "repo": engine["repo"], "commit": engine["commit"]}],
            "models": [{"id": model["id"], "source": "managed", "repo": model["repo"], "revision": model["revision"],
                        "codecRevision": model["codecRevision"]}], "libraries": [],
        })
        with patch.object(inference_module, "shutdown_inference_worker") as stop:
            response = self.client.put("/api/tts/defaults", json={"model_id": model["id"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["defaultModelId"], model["id"])
        self.assertEqual(response.json()["activeModelId"], model["id"])
        self.assertIsNone(response.json()["projectSelection"])
        self.assertNotIn("ttsSelection", json.loads(constants.PROJECT_FILE.read_text(encoding="utf-8")))
        stop.assert_called_once()

    def test_project_switch_drives_the_next_worker_checkpoint(self) -> None:
        catalog = app_module.tts_catalog()
        engine, model = catalog["engines"][0], catalog["models"][0]
        engine_path = self.root / "engine"
        model_path = self.root / "model"
        codec_path = self.root / "codec"
        tokenizer_path = self.root / "tokenizer"
        engine_path.mkdir()
        model_path.mkdir()
        codec_path.mkdir()
        tokenizer_path.mkdir()
        (engine_path / "infer.py").write_text("", encoding="utf-8")
        (model_path / "model.safetensors").write_bytes(b"model")
        (codec_path / "weights.pth").write_bytes(b"codec")
        python_path = self.root / "python"
        python_path.write_text("", encoding="utf-8")
        app_module.write_tts_registry({
            "version": 2, "defaultEngineId": engine["id"], "defaultModelId": None,
            "engines": [{"id": engine["id"], "source": "managed", "repo": engine["repo"], "commit": engine["commit"],
                         "path": str(engine_path), "pythonPath": str(python_path)}],
            "models": [{"id": model["id"], "source": "managed", "repo": model["repo"], "revision": model["revision"],
                        "codecRevision": model["codecRevision"], "path": str(model_path), "codecPath": str(codec_path),
                        "tokenizerPath": str(tokenizer_path)}], "libraries": [],
        })
        self.client.put("/api/project/tts-selection", json={"model_id": model["id"]}).raise_for_status()

        with patch.object(runtime_state, "INFERENCE_WORKER", None), patch.object(inference_module.subprocess, "Popen") as popen:
            inference_module.inference_worker_locked(engine_path)

        environment = popen.call_args.kwargs["env"]
        self.assertEqual(environment["IRODORI_TTS_CHECKPOINT"], str(model_path / "model.safetensors"))
        self.assertEqual(environment["IRODORI_TTS_CODEC"], str(codec_path / "weights.pth"))
        self.assertEqual(environment["IRODORI_TTS_TOKENIZER"], str(tokenizer_path))

    def test_managed_model_without_tokenizer_path_uses_bundled_tokenizer(self) -> None:
        catalog = app_module.tts_catalog()
        engine, model = catalog["engines"][0], catalog["models"][0]
        engine_path = self.root / "engine"
        model_path = self.root / "model"
        codec_path = self.root / "codec"
        tokenizer_path = model_path / "tokenizer"
        engine_path.mkdir()
        model_path.mkdir()
        codec_path.mkdir()
        tokenizer_path.mkdir()
        (engine_path / "infer.py").write_text("", encoding="utf-8")
        (model_path / "model.safetensors").write_bytes(b"model")
        (codec_path / "weights.pth").write_bytes(b"codec")
        python_path = self.root / "python"
        python_path.write_text("", encoding="utf-8")
        app_module.write_tts_registry({
            "version": 2, "defaultEngineId": engine["id"], "defaultModelId": model["id"],
            "engines": [{"id": engine["id"], "source": "managed", "repo": engine["repo"], "commit": engine["commit"],
                         "path": str(engine_path), "pythonPath": str(python_path)}],
            "models": [{"id": model["id"], "source": "managed", "repo": model["repo"], "revision": model["revision"],
                        "codecRevision": model["codecRevision"], "path": str(model_path), "codecPath": str(codec_path)}],
            "libraries": [],
        })

        with patch.object(runtime_state, "INFERENCE_WORKER", None), patch.object(inference_module.subprocess, "Popen") as popen:
            inference_module.inference_worker_locked(engine_path)

        self.assertEqual(popen.call_args.kwargs["env"]["IRODORI_TTS_TOKENIZER"], str(tokenizer_path))




if __name__ == "__main__":
    unittest.main()

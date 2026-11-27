from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import copy
import tempfile
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
from server.modules import tts_libraries as tts_libraries_module


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

    def test_catalog_pins_revisions_and_enables_hashed_install(self) -> None:
        catalog = self.client.get("/api/tts/catalog").json()
        self.assertEqual(catalog["version"], 2)
        self.assertTrue(catalog["engines"][0]["commit"].startswith("8224daf"))
        self.assertEqual(catalog["engines"][1]["commit"], "89f9d8fbd4d51ea019867ee1197725ede1df13c5")
        self.assertEqual(catalog["engines"][1]["archiveSha256"], "5125a538d00fedce4bd75dc20115e4d042d310cadfbffbbeeb257645f06671f0")
        self.assertEqual(catalog["engines"][0]["archiveSha256"], "38ab365dae85483713196125438068a51b831451817a2e7447e04ec2bcde6f9b")
        self.assertEqual(catalog["models"][0]["revision"], "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b")
        self.assertTrue(catalog["engines"][0]["installable"])
        self.assertEqual([item["generation"] for item in catalog["models"]], ["v4.1", "v4.1-mf", "v4.1", "v4", "v3", "v3", "v4"])
        self.assertEqual([item["recommendedOrder"] for item in catalog["models"]], list(range(1, 8)))
        self.assertEqual([item["legacy"] for item in catalog["models"]], [False, False, False, True, True, True, False])
        self.assertEqual([item["generation"] for item in catalog["models"] if not item["legacy"]], ["v4.1", "v4.1-mf", "v4.1", "v4"])
        self.assertEqual(
            [(item["author"], item["releasedAt"]) for item in catalog["models"][:3]],
            [("Aratako", "2026-08-11"), ("Aratako", "2026-09-12"), ("phasefield-audio", "2026-09-04")],
        )
        self.assertEqual(catalog["models"][1]["supportedEngineIds"], [catalog["engines"][1]["id"]])
        self.assertEqual({key: catalog["models"][1][key] for key in ("flowParameterization", "fixedSteps", "supportsRuntimeCfg", "supportsQualityPresets")}, {"flowParameterization": "meanflow", "fixedSteps": 4, "supportsRuntimeCfg": False, "supportsQualityPresets": False})
        self.assertFalse(any("Quantized" in item["repo"] or "v1" in item["repo"] for item in catalog["models"]))
        anime = catalog["models"][2]
        self.assertEqual(anime["repo"], "phasefield-audio/Irodori-TTS-v4.1-Anime")
        self.assertEqual(anime["revision"], "6b259f5baa5e236b3d14cbd1f8555ca87d92b530")
        self.assertEqual(anime["modelSha256"], "5630aa0a661930ff678a1d1f1893876e24520f4776d4fcc25ca54e6ab9f41f37")
        self.assertEqual((anime["publisher"], anime["provenance"]), ("phasefield-audio", "third-party-finetune"))
        self.assertIn("Aratako氏による制作・公式配布ではありません", anime["notice"])
        self.assertEqual(anime["supportedEngineIds"], [catalog["engines"][0]["id"]])
        self.assertEqual(anime["downloadFiles"], ["model.safetensors", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json", "README.md"])
        self.assertEqual(
            [(item.get("tagline"), item.get("description")) for item in catalog["models"][:3]],
            [
                ("品質を重視した標準モデル", "音声品質を重視した標準モデルです。どれを選ぶか迷った場合におすすめです。"),
                ("生成速度を重視した高速モデル", "生成速度を重視した高速モデルです。待ち時間を短くしたい場合に適しています。"),
                ("アニメ調の音声表現に特化した第三者モデル", "アニメ調の音声データで追加学習された第三者モデルです。"),
            ],
        )
        self.assertTrue(all("durationPrediction" not in item for item in catalog["models"]))
        self.assertFalse(any("v2" in item["repo"].lower() for item in catalog["models"]))
        capabilities = [(item["referenceVoice"], item["voiceDesign"], item["combinedReferenceCaption"]) for item in catalog["models"]]
        self.assertEqual(capabilities, [(True, True, True), (True, True, True), (True, True, True), (True, True, True), (True, True, True), (True, False, False), (True, True, True)])
        variants = catalog["models"][0]["variants"]
        self.assertEqual([item["id"] for item in variants if item.get("visible", True)], ["pytorch-fp32", "mlx-fp16", "mlx-8bit", "mlx-fp32"])
        derived = next(item for item in variants if item["id"] == "mlx-fp32")
        self.assertTrue(derived["derivedLocal"])
        self.assertTrue(derived["loraSupported"])
        self.assertFalse(derived["available"])
        self.assertEqual(derived["modelSha256"], catalog["models"][0]["modelSha256"])
        self.assertEqual(derived["sizeBytes"], 0)
        self.assertTrue(variants[1]["loraSupported"])
        self.assertFalse(variants[2]["loraSupported"])
        self.assertEqual(variants[1]["revision"], "8be8d91091380115f1ac77aeb6604ed588d05372")
        self.assertEqual(variants[1]["runtimePackage"], "mlx-audio==0.5.0")
        self.assertEqual(next(item["sha256"] for item in variants[1]["artifactFiles"] if item["path"] == "model.safetensors"), "99e022893ed27353aea6fca3897ee94c62bbaa568d705d230ee9b69f80a3a3bf")
        self.assertEqual(next(item["sha256"] for item in variants[1]["artifactFiles"] if item["path"] == "README.md"), "fe73fe9bd25bd749d5267801621202a58d8e76a079d48ff8b5b2d404c8a7d3d2")
        self.assertEqual(variants[2]["revision"], "c81956b675ce21422c305ef683fb2ac59d7faf6a")
        self.assertEqual(next(item["sha256"] for item in variants[2]["artifactFiles"] if item["path"] == "model.safetensors"), "b24b776dda4a03c12174896f0e00412b9d3521abca11fadab32ea715144d3ab0")

    def test_version_two_model_card_migrates_to_fp32_variant_without_changing_identity(self) -> None:
        model = app_module.tts_catalog()["models"][0]
        app_module.write_tts_registry({"version": 2, "defaultEngineId": None, "defaultModelId": model["id"], "engines": [], "libraries": [], "models": [{
            "id": model["id"], "displayName": model["displayName"], "source": "managed", "repo": model["repo"],
            "revision": model["revision"], "path": "/old/model", "diskBytes": 123, "verification": "verified",
        }]})
        migrated = app_module.read_tts_registry()
        self.assertEqual(migrated["version"], 3)
        self.assertEqual(migrated["models"][0]["activeVariantId"], "pytorch-fp32")
        self.assertEqual(migrated["models"][0]["installedVariants"][0]["path"], "/old/model")

    def test_active_variant_switch_is_global_and_stops_worker(self) -> None:
        model = app_module.tts_catalog()["models"][0]
        variants = [{"id": item["id"], "backend": item["backend"], "precision": item["precision"], "repo": item["repo"],
                     "revision": item["revision"], "optimizationProfile": item["runtimeProfile"]} for item in model["variants"]]
        app_module.write_tts_registry({"version": 3, "defaultEngineId": None, "defaultModelId": model["id"], "engines": [], "libraries": [], "models": [{
            "id": model["id"], "displayName": model["displayName"], "source": "managed", "repo": model["repo"],
            "revision": model["revision"], "verification": "verified", "activeVariantId": "pytorch-fp32", "installedVariants": variants,
        }]})
        with patch.object(inference_module, "shutdown_inference_worker") as stop:
            response = self.client.put(f"/api/tts/models/{model['id']}/active-variant", json={"variant_id": "mlx-fp16"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["models"][0]["activeVariantId"], "mlx-fp16")
        stop.assert_called_once()

    def test_model_only_selection_resolves_managed_engine(self) -> None:
        catalog = app_module.tts_catalog()
        engine, model = catalog["engines"][0], catalog["models"][5]
        app_module.write_tts_registry({"version": 1, "defaultEngineId": engine["id"], "defaultModelId": None,
            "engines": [{"id": engine["id"], "source": "managed", "repo": engine["repo"], "commit": engine["commit"]}],
            "models": [{"id": model["id"], "source": "managed", "repo": model["repo"], "revision": model["revision"], "codecRevision": model["codecRevision"]}]})
        response = self.client.put("/api/project/tts-selection", json={"model_id": model["id"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine"]["commit"], engine["commit"])
        self.assertEqual(self.client.get("/api/tts/registry").json()["selectedModelCapabilities"]["voiceDesign"], False)

    def test_registry_view_backfills_catalog_release_metadata(self) -> None:
        model = app_module.tts_catalog()["models"][0]
        app_module.write_tts_registry({
            "version": 2,
            "defaultEngineId": None,
            "defaultModelId": model["id"],
            "engines": [],
            "models": [{
                "id": model["id"], "displayName": model["displayName"], "source": "managed",
                "repo": model["repo"], "revision": model["revision"], "verification": "verified",
            }],
            "libraries": [],
        })

        stored_model = self.client.get("/api/tts/registry").json()["models"][0]

        self.assertEqual((stored_model["author"], stored_model["releasedAt"]), ("Aratako", "2026-08-11"))
        self.assertEqual(stored_model["tagline"], "品質を重視した標準モデル")

    def test_meanflow_model_selection_resolves_its_new_engine(self) -> None:
        catalog = app_module.tts_catalog()
        rf_engine, mf_engine, mf_model = catalog["engines"][0], catalog["engines"][1], catalog["models"][1]
        app_module.write_tts_registry({
            "version": 2,
            "defaultEngineId": rf_engine["id"],
            "defaultModelId": None,
            "engines": [
                {"id": engine["id"], "source": "managed", "repo": engine["repo"], "commit": engine["commit"]}
                for engine in (rf_engine, mf_engine)
            ],
            "models": [{"id": mf_model["id"], "source": "managed", "repo": mf_model["repo"], "revision": mf_model["revision"], "codecRevision": mf_model["codecRevision"], "engineId": mf_engine["id"]}],
            "libraries": [],
        })
        response = self.client.put("/api/project/tts-selection", json={"model_id": mf_model["id"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engine"]["commit"], mf_engine["commit"])
        capabilities = self.client.get("/api/tts/registry").json()["selectedModelCapabilities"]
        self.assertEqual((capabilities["flowParameterization"], capabilities["fixedSteps"]), ("meanflow", 4))

    def test_catalog_rejects_bad_signature_source_and_hash(self) -> None:
        catalog = app_module.tts_catalog()
        with self.assertRaises(ValueError):
            app_module.validate_tts_catalog(catalog, signature_verified=False)
        unknown = copy.deepcopy(catalog)
        unknown["engines"][0]["repo"] = "attacker/Irodori-TTS"
        with self.assertRaises(ValueError):
            app_module.validate_tts_catalog(unknown, signature_verified=True)
        corrupted = copy.deepcopy(catalog)
        corrupted["models"][0]["modelSha256"] = "not-a-hash"
        with self.assertRaises(ValueError):
            app_module.validate_tts_catalog(corrupted, signature_verified=True)
        future = copy.deepcopy(catalog)
        future["engines"][0]["minimumScenaVersion"] = "99.0.0"
        validated = app_module.validate_tts_catalog(future, signature_verified=True)
        self.assertFalse(validated["engines"][0]["installable"])

    def test_v2_download_identity_is_not_accepted(self) -> None:
        model_id = "Aratako/Irodori-TTS-500M-v2@8fd631cafb911dde466bc30dd558a0dc55e8ccae"
        response = self.client.post(f"/api/tts/model/{model_id}/downloads")
        self.assertEqual(response.status_code, 404)

    def test_v2_hash_is_not_accepted_for_external_registration(self) -> None:
        root, engine, model, codec = self._external_library_fixture()
        registry = self.client.post("/api/tts/libraries", json={"root": str(root), "engine_path": str(engine)}).json()
        library_id = registry["libraries"][0]["id"]
        with patch.object(tts_libraries_module, "_sha256", return_value="e5add885303babe328eae2c426475e41bc2f2aca2bcb010a2ceb6b6ddd1b8d9c"):
            job = self.client.post(f"/api/tts/libraries/{library_id}/models", json={"model_path": str(model), "codec_path": str(codec)}).json()
            for _ in range(100):
                job = self.client.get(f"/api/tts/library-model-jobs/{job['id']}").json()
                if job["state"] not in {"queued", "running", "cancelling"}:
                    break
                time.sleep(0.01)
        self.assertEqual(job["state"], "failed")
        self.assertIn("検証済みハッシュと一致しません", job["error"])

    def test_legacy_engine_migrates_and_selection_is_portable(self) -> None:
        engine = self.root / "Irodori-TTS"
        engine.mkdir()
        (engine / "infer.py").write_text("", encoding="utf-8")
        (self.root / "connection-settings.json").write_text(json.dumps({"engineDir": str(engine)}), encoding="utf-8")
        registry = self.client.get("/api/tts/registry").json()
        card_id = registry["engines"][0]["id"]
        self.client.put("/api/tts/defaults", json={"engine_id": card_id, "model_id": None}).raise_for_status()
        selection = self.client.put("/api/project/tts-selection", json={"engine_id": card_id, "model_id": None}).json()
        self.assertEqual(selection["engine"]["externalId"], card_id)
        self.assertNotIn(str(engine), json.dumps(selection))
        response = self.client.delete(f"/api/tts/engine/{card_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engines"], [])
        self.assertIsNone(response.json()["defaultEngineId"])
        self.assertNotIn("ttsSelection", app_module.read_project())
        self.assertEqual(app_module.read_connection_settings()["engineDir"], "")
        self.assertTrue(engine.is_dir())
        self.assertEqual(self.client.get("/api/tts/registry").json()["engines"], [])

    def test_managed_engine_can_be_removed_while_selected(self) -> None:
        commit = "a" * 40
        engine = self.root / "tts/engines" / commit
        environment = self.root / "tts/environments" / commit
        engine.mkdir(parents=True)
        (environment / "bin").mkdir(parents=True)
        (engine / "infer.py").write_text("", encoding="utf-8")
        (environment / "bin/python").write_text("", encoding="utf-8")
        card_id = f"Aratako/Irodori-TTS@{commit}"
        app_module.write_tts_registry({
            "version": 1, "defaultEngineId": card_id, "defaultModelId": None,
            "engines": [{"id": card_id, "source": "managed", "repo": "Aratako/Irodori-TTS",
                         "commit": commit, "path": str(engine), "pythonPath": str(environment / "bin/python")}],
            "models": [],
        })
        project = app_module.read_project()
        project["ttsSelection"] = {"engine": {"repo": "Aratako/Irodori-TTS", "commit": commit}, "model": None}
        app_module.write_project(project)

        response = self.client.delete(f"/api/tts/engine/{card_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["engines"], [])
        self.assertNotIn("ttsSelection", app_module.read_project())
        self.assertFalse(engine.exists())
        self.assertFalse(environment.exists())

    def test_external_library_records_observed_engine_commit(self) -> None:
        root, engine, _model, _codec = self._external_library_fixture()
        commit = "b" * 40
        with patch.object(tts_libraries_module.subprocess, "check_output", return_value=f"{commit}\n"):
            response = self.client.post(
                "/api/tts/libraries",
                json={"root": str(root), "engine_path": str(engine)},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["libraries"][0]["engineCommit"], commit)




if __name__ == "__main__":
    unittest.main()

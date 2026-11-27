from __future__ import annotations

import scena_test_isolation  # noqa: F401
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
from server.modules import tts_registry as tts_registry_module


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

    def test_engine_scan_skips_venv_and_discovers_standard_huggingface_cache(self) -> None:
        root, engine, _, _ = self._external_library_fixture()
        for index in range(2600):
            (engine / f".venv/lib/package-{index}").mkdir(parents=True)
        hf_home = self.root / "huggingface"
        model = hf_home / "hub/models--Aratako--Irodori-TTS-v4.1-Small/snapshots/revision"
        legacy_model = hf_home / "hub/models--Aratako--Irodori-TTS-500M-v3/snapshots/revision"
        unsupported_v2_model = hf_home / "hub/models--Aratako--Irodori-TTS-500M-v2/snapshots/revision"
        legacy_tokenizer = hf_home / "hub/models--llm-jp--llm-jp-3-150m/snapshots/revision"
        codec = hf_home / "hub/models--Aratako--Semantic-DACVAE-Japanese-32dim/snapshots/revision"
        (model / "tokenizer").mkdir(parents=True)
        legacy_model.mkdir(parents=True)
        unsupported_v2_model.mkdir(parents=True)
        legacy_tokenizer.mkdir(parents=True)
        codec.mkdir(parents=True)
        (model / "model.safetensors").write_bytes(b"cached-model")
        (legacy_model / "model.safetensors").write_bytes(b"legacy-model")
        (unsupported_v2_model / "model.safetensors").write_bytes(b"unsupported-v2-model")
        (legacy_tokenizer / "tokenizer.json").write_text("{}", encoding="utf-8")
        (codec / "weights.pth").write_bytes(b"cached-codec")
        with patch.dict(os.environ, {"HF_HOME": str(hf_home)}):
            scan = self.client.post("/api/tts/libraries/scan", json={"path": str(root)}).json()
            self.assertFalse(scan["limited"])
            cached_models = [item for item in scan["models"] if "huggingface" in item["path"]]
            self.assertEqual({Path(item["path"]).resolve() for item in cached_models}, {model.resolve(), legacy_model.resolve()})
            modern_candidate = next(item for item in cached_models if Path(item["path"]).resolve() == model.resolve())
            self.assertEqual(modern_candidate["displayName"], "Irodori-TTS v4.1 Small")
            self.assertEqual(modern_candidate["repo"], "Aratako/Irodori-TTS-v4.1-Small")
            self.assertEqual(modern_candidate["revision"], "revision")
            legacy_candidate = next(item for item in cached_models if Path(item["path"]).resolve() == legacy_model.resolve())
            self.assertEqual(legacy_candidate["displayName"], "Irodori-TTS v3 Base")
            self.assertEqual(Path(legacy_candidate["tokenizerPath"]).resolve(), legacy_tokenizer.resolve())
            self.assertEqual([Path(item["path"]).resolve() for item in scan["codecs"] if "huggingface" in item["path"]], [codec.resolve()])
            registry = self.client.post("/api/tts/libraries", json={"root": str(root), "engine_path": str(engine)}).json()
            library_id = registry["libraries"][0]["id"]
            catalog = app_module.tts_catalog()
            catalog["models"][0]["modelSha256"] = hashlib.sha256(b"cached-model").hexdigest()
            catalog["models"][0]["codecSha256"] = hashlib.sha256(b"cached-codec").hexdigest()
            with patch.object(tts_registry_module, "tts_catalog", return_value=catalog):
                job = self.client.post(f"/api/tts/libraries/{library_id}/models", json={"model_path": str(model), "codec_path": str(codec)}).json()
                for _ in range(100):
                    job = self.client.get(f"/api/tts/library-model-jobs/{job['id']}").json()
                    if job["state"] not in {"queued", "running", "cancelling"}:
                        break
                    time.sleep(0.01)
            self.assertEqual(job["state"], "complete")




if __name__ == "__main__":
    unittest.main()

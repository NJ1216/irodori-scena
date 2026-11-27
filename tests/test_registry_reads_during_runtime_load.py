"""Reading registries must not wait for a model load that holds the runtime lock (Windows startup preload)."""
from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import keyring
from fastapi.testclient import TestClient

import server.app as app_module
from server.modules import constants, llm_registry, llm_runtime_binding
from server.modules import llm_registry_io as registry_io
from server.modules import model_runtime_jobs as jobs


class RegistryReadsDuringRuntimeLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for target in (
            patch.object(llm_registry, "REGISTRY_FILE", root / "registry.json"),
            patch.object(llm_registry.keyring, "get_password", return_value=None),
            patch.object(llm_registry.keyring, "set_password"),
            patch.object(jobs.sys, "platform", "win32"),
            patch("server.modules.local_llm_runtime.platform.system", return_value="Windows"),
            patch.object(jobs, "JOBS", {}),
            patch("server.modules.constants.LOCAL_LLM_ROOT", root / "llm"),
            patch("server.modules.llama_cpp_runtime.selected_backend", return_value="cpu"),
            patch("server.modules.llama_cpp_runtime.recommended_backend", return_value="cpu"),
            patch("server.modules.llama_cpp_runtime.llama_cpp_runtime_status",
                  return_value={"ready": True, "version": "test", "job": {"state": "idle"}}),
        ):
            target.start()
            self.addCleanup(target.stop)
        endpoint = llm_registry.create_llm_endpoint({"provider": "ollama", "displayName": "Local",
                                                     "baseUrl": "http://127.0.0.1:11434/v1"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model-a"})
        saved = json.loads(llm_registry.REGISTRY_FILE.read_text(encoding="utf-8"))
        for item in saved["cards"]:
            if item["id"] == card["id"]:
                item["runtimeId"] = "llama.cpp-test-cpu"
        llm_registry.REGISTRY_FILE.write_text(json.dumps(saved), encoding="utf-8")
        self.card_id = card["id"]

    def _read_while_runtime_lock_is_held(self, read):
        held, release, result = threading.Event(), threading.Event(), {}

        def load_model() -> None:  # stands in for prepare_irodori_worker / CUDA calibration on Windows
            with llm_runtime_binding.LOCK:
                held.set()
                release.wait(10)

        loader = threading.Thread(target=load_model, daemon=True)
        loader.start()
        self.assertTrue(held.wait(5))
        reader = threading.Thread(target=lambda: result.setdefault("value", read()), daemon=True)
        reader.start()
        reader.join(2)
        finished = not reader.is_alive()
        release.set()
        loader.join(5)
        reader.join(5)
        self.assertTrue(finished, "the registry read waited for the model load")
        return result["value"]

    def test_public_llm_registry_does_not_wait_for_a_model_load(self) -> None:
        registry = self._read_while_runtime_lock_is_held(llm_registry.public_llm_registry)
        card = next(item for item in registry["cards"] if item["id"] == self.card_id)
        self.assertEqual(card["runtime"]["state"], "ready")

    def test_runtime_status_restores_saved_jobs_once_without_the_runtime_lock(self) -> None:
        # The real, lock-taking set_llm_test_status runs here: a restore that called it inline waited for the
        # load (and could deadlock against start_model_runtime, which holds the lock and then restores).
        llm_registry.set_llm_test_status(self.card_id, {"state": "passed", "checkedAt": 1, "errorCategory": None})
        path = jobs._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({self.card_id: {"cardId": self.card_id, "state": "running"}}), encoding="utf-8")
        status = self._read_while_runtime_lock_is_held(
            lambda: jobs.model_runtime_status({"id": self.card_id, "runtimeId": "llama.cpp-test-cpu"}))
        self.assertEqual(status["job"]["state"], "interrupted")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and self._test_state() != "untested":
            time.sleep(0.02)
        self.assertEqual(self._test_state(), "untested", "the interrupted card keeps a stale test result")

    def _test_state(self) -> str | None:
        card = next(item for item in llm_registry.read_llm_registry()["cards"] if item["id"] == self.card_id)
        return (card.get("testStatus") or {}).get("state")

    def test_card_invalidation_is_shown_at_once_and_saved_after_the_load(self) -> None:
        model = llm_registry.REGISTRY_FILE.parent / "local-model"
        model.mkdir()
        (model / "config.json").write_text("{}", encoding="utf-8")
        endpoint = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "local", "source": "external",
                                             "localMetadata": {"path": str(model), "fingerprint": "old"}})
        def saved() -> str:
            cards = json.loads(llm_registry.REGISTRY_FILE.read_text(encoding="utf-8"))["cards"]
            return next(item for item in cards if item["id"] == card["id"])["localMetadata"]["fingerprint"]
        shown = self._read_while_runtime_lock_is_held(llm_registry.public_llm_registry)
        self.assertNotEqual(next(item for item in shown["cards"] if item["id"] == card["id"])["localMetadata"]["fingerprint"], "old")
        self.assertEqual(saved(), "old")
        llm_registry.public_llm_registry()
        self.assertNotEqual(saved(), "old")

    def test_registry_file_reads_and_replacements_never_overlap(self) -> None:
        # Windows opens files without FILE_SHARE_DELETE, so a replace during an unlocked read fails.
        observed = []
        original_replace, original_read = Path.replace, Path.read_text

        def replace(path, target):
            observed.append(("replace", registry_io.FILE_LOCK.locked()))
            return original_replace(path, target)

        def read_text(path, *args, **kwargs):
            if path == llm_registry.REGISTRY_FILE:
                observed.append(("read", registry_io.FILE_LOCK.locked()))
            return original_read(path, *args, **kwargs)

        with patch.object(Path, "replace", replace), patch.object(Path, "read_text", read_text):
            llm_registry.write_llm_registry(llm_registry.read_llm_registry())
        self.assertTrue(observed)
        self.assertTrue(all(held for _kind, held in observed), observed)


class StartupScreenReadsDuringRuntimeLoadTests(unittest.TestCase):
    """The six reads the studio makes before it leaves "ローカルプロジェクトを読み込み中…"."""

    BOOTSTRAP = ("/api/project", "/api/project/workspace", "/api/settings/engine-directory",
                 "/api/llm/registry", "/api/tts/registry", "/api/tts/catalog",
                 # The footer polls these from the first frame.
                 "/api/system/memory", "/api/llm/session-usage", "/api/tts/runtime/status")

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for target in (
            patch("server.modules.tts_runtime.start_tts_prepare", return_value={}),
            patch.dict(os.environ, {"HF_HOME": str(root / "empty-huggingface")}),
            patch.object(keyring, "get_password", return_value=None),
            patch.object(llm_registry, "REGISTRY_FILE", root / "llm-registry.json"),
            patch.object(constants, "DATA_ROOT", root),
            patch.object(constants, "APP_STATE_FILE", root / "app-state.json"),
            patch.object(constants, "TTS_ASSETS_ROOT", root / "tts"),
            patch.object(constants, "TTS_ENGINES_ROOT", root / "tts/engines"),
            patch.object(constants, "TTS_ENVIRONMENTS_ROOT", root / "tts/environments"),
            patch.object(constants, "TTS_MODELS_ROOT", root / "tts/models"),
            patch.object(constants, "TTS_CODECS_ROOT", root / "tts/codecs"),
            patch.object(constants, "TTS_DOWNLOADS_ROOT", root / "tts/downloads"),
            patch.object(constants, "TTS_REGISTRY_FILE", root / "tts/registry.json"),
            patch.object(constants, "PROJECT_FILE", root / "project.json"),
            patch.object(constants, "MEDIA_ROOT", root / "media"),
            patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
            patch.object(constants, "ACTIVE_PROJECT_PATH", None),
            patch.object(constants, "CONNECTION_SETTINGS_FILE", root / "connection-settings.json"),
            patch("server.modules.constants.LOCAL_LLM_ROOT", root / "llm"),
            patch.object(jobs.sys, "platform", "win32"),
            patch("server.modules.local_llm_runtime.platform.system", return_value="Windows"),
        ):
            target.start()
            self.addCleanup(target.stop)
        app_module.ensure_data_root()
        app_module.ensure_tts_storage()
        self.client = TestClient(app_module.app)

    def test_startup_reads_answer_while_a_model_load_holds_the_runtime_lock(self) -> None:
        held, release, statuses = threading.Event(), threading.Event(), {}

        def load_model() -> None:
            with llm_runtime_binding.LOCK:
                held.set()
                release.wait(15)

        loader = threading.Thread(target=load_model, daemon=True)
        loader.start()
        self.assertTrue(held.wait(5))
        readers = [threading.Thread(target=lambda path=path: statuses.__setitem__(path, self.client.get(path).status_code),
                                    daemon=True) for path in self.BOOTSTRAP]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join(3)
        waiting = [path for path in self.BOOTSTRAP if path not in statuses]
        release.set()
        loader.join(5)
        self.assertEqual(waiting, [])
        self.assertEqual(set(statuses.values()), {200}, statuses)


if __name__ == "__main__":
    unittest.main()

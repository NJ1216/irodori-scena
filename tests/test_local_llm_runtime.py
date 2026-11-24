from __future__ import annotations

import os
import io
import tempfile
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app import app
from server.modules import local_llm_runtime, local_llm_storage, omlx_environment
from server.modules.local_llm_runtime import local_llm_capabilities, resolve_local_llm_request
from server.modules.models import ModelListRequest, ThemeSuggestionRequest
from server.modules.local_llm_storage import _scan_library


class LocalLlmCapabilityTests(unittest.TestCase):
    def test_runtime_command_uses_the_active_managed_environment(self) -> None:
        runtime_python = Path("/managed/omlx/bin/python")
        with (
            patch.dict(os.environ, {"SCENA_OMLX_LAUNCHER": "/app/omlx-sidecar.py"}, clear=False),
            patch("server.modules.omlx_environment.omlx_environment_status", return_value={"ready": True}),
            patch("server.modules.omlx_environment.omlx_environment_python", return_value=runtime_python),
        ):
            os.environ.pop("SCENA_OMLX_EXECUTABLE", None)
            command = local_llm_runtime._runtime_command()
        self.assertEqual(command, [str(runtime_python), "/app/omlx-sidecar.py"])

    def test_hot_cache_budget_tracks_the_memory_guard_without_ssd_cache(self) -> None:
        self.assertEqual(local_llm_runtime._hot_cache_size("safe"), "2GB")
        self.assertEqual(local_llm_runtime._hot_cache_size("balanced"), "4GB")
        self.assertEqual(local_llm_runtime._hot_cache_size("aggressive"), "8GB")
        self.assertEqual(local_llm_runtime._hot_cache_size("off"), "2GB")

    def test_mac_memory_profiles(self) -> None:
        for memory in (16, 24, 32, 64):
            with self.subTest(memory=memory):
                result = local_llm_capabilities(memory, "Darwin")
                self.assertNotIn("recommendedModel", result)
                self.assertNotIn("memoryGiB", result)
                self.assertTrue(result["sequentialResidency"])

    def test_existing_and_managed_providers_validate(self) -> None:
        for provider in ("ollama", "lmstudio", "openai", "scena-local"):
            request = ModelListRequest(base_url="http://localhost/v1", provider=provider)
            self.assertEqual(request.provider, provider)

    def test_managed_request_resolves_without_exposing_saved_url(self) -> None:
        request = ThemeSuggestionRequest(
            base_url="http://scena.local/v1",
            model="gemma-4-12b-it-4bit",
            provider="scena-local",
            character_ids=["cast-a"],
        )
        with (
            patch.dict(os.environ, {"SCENA_LOCAL_LLM_ENDPOINT": "http://127.0.0.1:9999/v1"}),
            patch("server.modules.local_llm_runtime.LOADED_MODEL", request.model),
            patch("server.modules.resource_coordinator.acquire_llm_memory"),
        ):
            resolved = resolve_local_llm_request(request)
        self.assertEqual(resolved.provider, "openai")
        self.assertEqual(resolved.base_url, "http://127.0.0.1:9999/v1")
        self.assertEqual(resolved.api_key, "")

    def test_managed_request_accepts_pronunciation_lightweight_request(self) -> None:
        request = SimpleNamespace(
            base_url="http://scena.local/v1",
            model="local-model",
            api_key="",
            provider="scena-local",
        )
        with (
            patch.dict(os.environ, {"SCENA_LOCAL_LLM_ENDPOINT": "http://127.0.0.1:9999/v1"}),
            patch("server.modules.local_llm_runtime.LOADED_MODEL", request.model),
            patch("server.modules.resource_coordinator.acquire_llm_memory"),
        ):
            resolved = resolve_local_llm_request(request)
        self.assertEqual(resolved.provider, "openai")
        self.assertEqual(resolved.base_url, "http://127.0.0.1:9999/v1")
        self.assertEqual(request.provider, "scena-local")
        self.assertEqual(request.base_url, "http://scena.local/v1")

    def test_stopped_managed_process_is_reloaded_even_when_model_identity_matches(self) -> None:
        request = SimpleNamespace(
            base_url="http://scena.local/v1",
            model="local-model",
            api_key="",
            provider="scena-local",
        )
        stopped = SimpleNamespace(poll=lambda: 7)
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(local_llm_runtime.platform, "system", return_value="Windows"),
            patch.object(local_llm_runtime, "LOADED_MODEL", request.model),
            patch.object(local_llm_runtime, "RUNTIME_PROCESS", stopped),
            patch.object(local_llm_runtime, "RUNTIME_PORT", 43123),
            patch.object(local_llm_runtime, "RUNTIME_API_KEY", "stale-key"),
            patch.object(local_llm_runtime, "stop_local_llm") as stop,
            patch.object(local_llm_runtime, "load_local_llm") as load,
            patch.object(local_llm_runtime, "_runtime_endpoint", return_value="http://127.0.0.1:43124/v1"),
            patch.object(local_llm_runtime, "local_llm_runtime_api_key", return_value="new-key"),
            patch("server.modules.llm_registry.resolve_llm_settings", return_value={"memoryGuard": "safe"}),
            patch("server.modules.resource_coordinator.acquire_llm_memory"),
        ):
            resolved = resolve_local_llm_request(request)
        stop.assert_called_once_with()
        load.assert_called_once_with("local-model", settings={"memoryGuard": "safe"})
        self.assertEqual((resolved.base_url, resolved.api_key), ("http://127.0.0.1:43124/v1", "new-key"))

    def test_lightweight_request_can_resolve_the_default_external_model(self) -> None:
        request = SimpleNamespace(base_url="", model="", api_key="", provider="openai")
        selected = {
            "baseUrl": "http://127.0.0.1:11434/v1",
            "model": "external-model",
            "apiKey": "key",
            "provider": "ollama",
        }
        with patch("server.modules.llm_registry.resolve_default_llm", return_value=selected):
            resolved = resolve_local_llm_request(request)
        self.assertEqual(resolved.provider, "ollama")
        self.assertEqual(resolved.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(resolved.model, "external-model")
        self.assertEqual(request.base_url, "")
        self.assertEqual(request.model, "")

    def test_runtime_metrics_uses_the_private_api_key(self) -> None:
        response = io.BytesIO(json.dumps({"activeMemoryBytes": 456, "modelMemoryBytes": 789}).encode())
        response.status = 200  # type: ignore[attr-defined]
        response.__enter__ = lambda value: value  # type: ignore[attr-defined]
        response.__exit__ = lambda *_args: None  # type: ignore[attr-defined]
        with (
            patch.object(local_llm_runtime, "local_llm_status", return_value={"running": True}),
            patch.object(local_llm_runtime, "_runtime_endpoint", return_value="http://127.0.0.1:8791/v1"),
            patch.object(local_llm_runtime, "RUNTIME_API_KEY", "private-key"),
            patch.object(local_llm_runtime.urllib.request, "urlopen", return_value=response) as opened,
        ):
            self.assertEqual(local_llm_runtime.local_llm_metal_memory(), 789)
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:8791/api/scena/metrics")
        self.assertEqual(request.headers["Authorization"], "Bearer private-key")

    def test_runtime_uses_an_available_port_unless_explicitly_configured(self) -> None:
        with patch.dict(os.environ, {}, clear=False), patch.object(local_llm_runtime.socket, "socket") as create_socket:
            os.environ.pop("SCENA_LOCAL_LLM_PORT", None)
            reservation = create_socket.return_value.__enter__.return_value
            reservation.getsockname.return_value = ("127.0.0.1", 43123)
            selected = local_llm_runtime._select_runtime_port()
        self.assertEqual(selected, 43123)
        reservation.bind.assert_called_once_with(("127.0.0.1", 0))
        with patch.dict(os.environ, {"SCENA_LOCAL_LLM_PORT": "9876"}):
            self.assertEqual(local_llm_runtime._select_runtime_port(), 9876)


class LocalLlmRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_capabilities_are_available_without_legacy_catalog(self) -> None:
        capability = self.client.get("/api/local-llm/capabilities")
        catalog = self.client.get("/api/local-llm/models")
        self.assertEqual(capability.status_code, 200)
        self.assertEqual(catalog.status_code, 404)
        self.assertIn("memoryOwner", capability.json())

    def test_recommended_runtime_null_tag_reaches_installer_as_none(self) -> None:
        expected = {"activeRuntimeId": None, "installedRuntimes": []}
        with patch.object(omlx_environment, "install_omlx_runtime", return_value=expected) as install:
            response = self.client.post("/api/local-llm/runtimes/install", json={"tag": None})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), expected)
        install.assert_called_once_with(None)

    def test_external_library_scan_finds_only_mlx_without_following_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "nested" / "gemma-mlx"
            model.mkdir(parents=True)
            (model / "config.json").write_text("{}", encoding="utf-8")
            (model / "model.safetensors").write_bytes(b"weights")
            gguf = root / "ollama"
            gguf.mkdir()
            (gguf / "model.gguf").write_bytes(b"gguf")
            (root / "cycle").symlink_to(root, target_is_directory=True)
            found, limited, gguf_only = _scan_library(root)
            self.assertEqual(found, [model.resolve()])
            self.assertFalse(limited)
            self.assertTrue(gguf_only)

    def test_external_scan_accepts_a_direct_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "nested" / "model"
            model.mkdir(parents=True)
            (model / "config.json").write_text(
                json.dumps({"_name_or_path": "google/gemma-4-26B-A4B-it", "quantization_config": {"bits": 6}}),
                encoding="utf-8",
            )
            (model / "weights.safetensors").write_bytes(b"weights")
            response = self.client.post("/api/llm/external/scan", json={"path": temporary})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["models"][0]["path"], str(model.resolve()))
        self.assertEqual(
            response.json()["models"][0]["inferredTags"],
            [
                {"kind": "family", "value": "Gemma 4"},
                {"kind": "parameters", "value": "26B"},
                {"kind": "quantization", "value": "6bit"},
                {"kind": "purpose", "value": "Instruct"},
            ],
        )

    def test_external_registration_persists_inferred_tags_in_card_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model = Path(temporary) / "Qwen-2.5-Coder-7B-Instruct-4bit"
            model.mkdir()
            (model / "config.json").write_text("{}", encoding="utf-8")
            (model / "weights.safetensors").write_bytes(b"weights")
            with (
                patch.object(local_llm_storage, "SETTINGS_FILE", Path(temporary) / "settings.json"),
                patch.object(local_llm_storage, "rebuild_local_llm_discovery"),
                patch("server.modules.llm_registry.register_local_llm_card", return_value={"id": "card"}) as register,
            ):
                local_llm_storage.register_external_llm_model(str(model))
        metadata = register.call_args.kwargs["metadata"]
        self.assertIn({"kind": "family", "value": "Qwen 2.5"}, metadata["inferredTags"])
        self.assertIn({"kind": "parameters", "value": "7B"}, metadata["inferredTags"])
        self.assertIn({"kind": "quantization", "value": "4bit"}, metadata["inferredTags"])

    def test_legacy_model_discovery_api_is_removed(self) -> None:
        self.assertEqual(self.client.post("/api/llm/models", json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()

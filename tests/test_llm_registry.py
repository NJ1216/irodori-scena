from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import llm_registry, llm_session_usage


class LlmRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        for name, value in (("_OPERATIONS", {}), ("_ORDER", [])):
            isolated = patch.object(llm_session_usage, name, value)
            isolated.start()
            self.addCleanup(isolated.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.file_patch = patch.object(llm_registry, "REGISTRY_FILE", Path(self.temporary.name) / "registry.json")
        self.file_patch.start()
        self.secrets: dict[tuple[str, str], str] = {}
        self.get_patch = patch.object(llm_registry.keyring, "get_password", side_effect=lambda service, account: self.secrets.get((service, account)))
        self.set_patch = patch.object(llm_registry.keyring, "set_password", side_effect=lambda service, account, value: self.secrets.__setitem__((service, account), value))
        self.get_patch.start()
        self.set_patch.start()
        self.delete_patch = patch.object(llm_registry.keyring, "delete_password", side_effect=lambda service, account: self.secrets.pop((service, account), None))
        self.delete_patch.start()

    def tearDown(self) -> None:
        self.get_patch.stop()
        self.set_patch.stop()
        self.delete_patch.stop()
        self.file_patch.stop()
        self.temporary.cleanup()

    def test_endpoint_secret_is_not_persisted_and_cards_share_it(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "ollama", "displayName": "Local", "baseUrl": "http://127.0.0.1:11434/v1", "credential": "secret"})
        first = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model-a"})
        second = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model-b"})
        persisted = llm_registry.REGISTRY_FILE.read_text()
        self.assertNotIn("secret", persisted)
        self.assertEqual(llm_registry.read_llm_registry()["defaultCardId"], first["id"])
        llm_registry.set_default_llm_card(second["id"])
        resolved = llm_registry.resolve_default_llm()
        self.assertEqual((resolved["model"], resolved["apiKey"]), ("model-b", "secret"))

    def test_public_creation_rejects_internal_endpoint_and_managed_source(self) -> None:
        with self.assertRaisesRegex(Exception, "ダウンロードまたは外部MLX登録"):
            llm_registry.create_remote_llm_endpoint({"provider": "scena-local"})
        internal = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        with self.assertRaisesRegex(Exception, "ダウンロードまたは外部MLX登録"):
            llm_registry.create_remote_llm_card({"endpointId": internal["id"], "modelId": "manual"})
        remote = llm_registry.create_llm_endpoint({"provider": "ollama", "baseUrl": "http://127.0.0.1:11434/v1"})
        card = llm_registry.create_remote_llm_card({"endpointId": remote["id"], "modelId": "server-model", "source": "managed"})
        self.assertEqual(card["source"], "remote")

    def test_endpoint_discovery_uses_keychain_secret_and_endpoint_can_be_deleted(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "ollama", "baseUrl": "http://127.0.0.1:11434/v1",
                                                     "credential": "secret"})
        with patch("server.modules.llm_client.list_llm_models", return_value=["one", "two"]) as listing:
            self.assertEqual(llm_registry.discover_llm_endpoint_models(endpoint["id"]), ["one", "two"])
        request = listing.call_args.args[0]
        self.assertEqual((request.provider, request.api_key), ("ollama", "secret"))
        registry = llm_registry.delete_llm_endpoint(endpoint["id"])
        self.assertEqual(registry["endpoints"], [])
        self.assertNotIn((llm_registry.deps.KEYCHAIN_SERVICE, f"llm-endpoint-{endpoint['id']}"), self.secrets)

    def test_remote_inspection_does_not_persist_connection_or_secret(self) -> None:
        with patch("server.modules.llm_client.list_llm_models", return_value=["one"]) as listing:
            models = llm_registry.inspect_remote_llm_models({
                "provider": "ollama", "baseUrl": "http://127.0.0.1:11434/v1", "credential": "secret",
            })
        self.assertEqual(models, ["one"])
        self.assertEqual(listing.call_args.args[0].api_key, "secret")
        self.assertFalse(llm_registry.REGISTRY_FILE.exists())
        self.assertEqual(self.secrets, {})

    def test_remote_setting_creates_card_endpoint_and_keychain_secret_together(self) -> None:
        result = llm_registry.create_remote_llm_setting({
            "provider": "openai", "baseUrl": "https://example.invalid/v1",
            "modelId": "server-model", "credential": "secret",
        })
        registry = result["registry"]
        self.assertEqual(registry["cards"][0]["displayName"], "server-model")
        self.assertEqual(len(registry["endpoints"]), 1)
        self.assertNotIn("secret", llm_registry.REGISTRY_FILE.read_text(encoding="utf-8"))
        account = f"llm-endpoint-{registry['endpoints'][0]['id']}"
        self.assertEqual(self.secrets[(llm_registry.deps.KEYCHAIN_SERVICE, account)], "secret")

    def test_failed_remote_addition_preserves_the_previous_selection(self) -> None:
        options = {"provider": "ollama", "baseUrl": "http://localhost:11434/v1", "modelId": "old-model"}
        original = llm_registry.create_remote_llm_setting(options)
        before = llm_registry.REGISTRY_FILE.read_text()
        with patch.object(llm_registry, "_write_registry", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                llm_registry.create_remote_llm_setting({**options, "modelId": "new-model"})
        self.assertEqual(llm_registry.REGISTRY_FILE.read_text(), before)
        self.assertEqual(llm_registry.read_llm_registry()["defaultCardId"], original["card"]["id"])

    def test_last_remote_card_removal_deletes_endpoint_secret_but_shared_endpoint_is_kept(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "ollama", "baseUrl": "http://localhost:11434/v1", "credential": "secret"})
        first = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "one"})
        second = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "two"})
        first_result = llm_registry.delete_llm_card(first["id"])
        self.assertEqual(len(first_result["registry"]["endpoints"]), 1)
        self.assertTrue(self.secrets)
        second_result = llm_registry.delete_llm_card(second["id"])
        self.assertEqual(second_result["registry"]["endpoints"], [])
        self.assertEqual(self.secrets, {})

    def test_endpoint_credential_can_be_saved_and_removed_from_keychain(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "openai", "baseUrl": "https://example.invalid/v1"})
        self.assertFalse(endpoint["hasCredential"])
        saved = llm_registry.save_llm_endpoint_credential(endpoint["id"], " new-secret ")
        self.assertTrue(saved["hasCredential"])
        self.assertNotIn("new-secret", llm_registry.REGISTRY_FILE.read_text(encoding="utf-8"))
        removed = llm_registry.delete_llm_endpoint_credential(endpoint["id"])
        self.assertFalse(removed["hasCredential"])
        self.assertNotIn((llm_registry.deps.KEYCHAIN_SERVICE, f"llm-endpoint-{endpoint['id']}"), self.secrets)

    def test_local_file_or_omlx_change_invalidates_basic_test(self) -> None:
        model = Path(self.temporary.name) / "model"
        model.mkdir()
        (model / "config.json").write_text("{}", encoding="utf-8")
        endpoint = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "local", "source": "external",
                                             "localMetadata": {"path": str(model), "fingerprint": "old", "omlxVersion": "old"}})
        llm_registry.set_llm_test_status(card["id"], {"state": "passed", "checkedAt": 123, "errorCategory": None})
        refreshed = llm_registry.public_llm_registry()["cards"][0]
        self.assertEqual(refreshed["testStatus"]["state"], "untested")
        self.assertNotEqual(refreshed["localMetadata"]["fingerprint"], "old")

    def test_new_local_model_starts_one_automatic_model_test(self) -> None:
        model = Path(self.temporary.name) / "model"
        model.mkdir()
        (model / "config.json").write_text("{}", encoding="utf-8")
        with patch("server.modules.model_runtime_jobs.start_model_runtime") as start:
            card = llm_registry.register_local_llm_card(
                "local", source="external", metadata={"path": str(model)},
            )
            same = llm_registry.register_local_llm_card(
                "local", source="external", metadata={"path": str(model)},
            )
        start.assert_called_once_with(card["id"], automatic=True)
        self.assertEqual(same["id"], card["id"])

    def test_unchanged_local_model_reuses_its_saved_fingerprint(self) -> None:
        model = Path(self.temporary.name) / "model"
        model.mkdir()
        (model / "config.json").write_text("{}", encoding="utf-8")
        endpoint = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "local", "source": "external",
                                      "localMetadata": {"path": str(model), "fingerprint": "old"}})
        with patch.object(llm_registry, "_local_fingerprint", wraps=llm_registry._local_fingerprint) as fingerprint:
            llm_registry.public_llm_registry()
            llm_registry.public_llm_registry()
        self.assertEqual(fingerprint.call_count, 1)

    def test_usage_history_is_secret_free_and_bounded(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "openai", "baseUrl": "https://example.invalid/v1"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model"})
        for index in range(25):
            llm_registry.record_llm_usage(card["id"], "theme", False, f"failure {index}")
        history = llm_registry.read_llm_registry()["cards"][0]["usageHistory"]
        self.assertEqual(len(history), 20)
        self.assertEqual(history[0]["error"], "failure 24")

    def test_feature_usage_is_recorded_only_after_operation_finishes(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "openai", "baseUrl": "https://example.invalid/v1"})
        llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model"})
        result = llm_registry.track_default_llm_usage("画像プロンプト提案", lambda: {"parsed": True})
        self.assertEqual(result, {"parsed": True})
        history = llm_registry.read_llm_registry()["cards"][0]["usageHistory"]
        self.assertEqual((history[0]["feature"], history[0]["success"]), ("画像プロンプト提案", True))

    def test_feature_failure_does_not_persist_exception_message(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "openai", "baseUrl": "https://example.invalid/v1"})
        llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model"})
        with self.assertRaisesRegex(RuntimeError, "secret prompt"):
            llm_registry.track_default_llm_usage("テーマ提案", lambda: (_ for _ in ()).throw(RuntimeError("secret prompt")))
        history = llm_registry.read_llm_registry()["cards"][0]["usageHistory"]
        self.assertEqual(history[0]["error"], "RuntimeError")
        self.assertNotIn("secret", llm_registry.REGISTRY_FILE.read_text())

    def test_compatibility_setting_change_invalidates_basic_test(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "openai", "baseUrl": "https://example.invalid/v1"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model"})
        registry = llm_registry.read_llm_registry()
        registry["cards"][0]["testStatus"] = {"state": "passed", "checkedAt": 123, "errorCategory": None}
        llm_registry._write_registry(registry)
        updated = llm_registry.update_llm_card(card["id"], {"settings": {"ttlSeconds": 600}})
        self.assertEqual(updated["testStatus"]["state"], "passed")
        updated = llm_registry.update_llm_card(card["id"], {"settings": {"thinking": True}})
        self.assertEqual(updated["testStatus"], {"state": "untested", "checkedAt": None, "errorCategory": None})

    def test_sampling_settings_are_validated_and_resolved_for_requests(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "ollama", "baseUrl": "http://localhost:11434/v1"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model"})
        updated = llm_registry.update_llm_card(card["id"], {"settings": {
            "temperature": 0.4, "topP": 0.9, "topK": 40, "minP": 0.05, "repetitionPenalty": 1.1,
        }, "displayName": "執筆用モデル"})
        self.assertEqual(updated["displayName"], "執筆用モデル")
        self.assertEqual(updated["settings"]["topK"], 40)
        resolved = llm_registry.resolve_llm_settings("ollama", "http://localhost:11434/v1/", "model")
        self.assertEqual((resolved["temperature"], resolved["repetitionPenalty"]), (0.4, 1.1))
        with self.assertRaisesRegex(Exception, "topP"):
            llm_registry.update_llm_card(card["id"], {"settings": {"topP": 1.5}})

    def test_retired_acceleration_setting_is_removed_when_registry_is_read(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "openai", "baseUrl": "https://example.invalid/v1"})
        llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model"})
        persisted = json.loads(llm_registry.REGISTRY_FILE.read_text(encoding="utf-8"))
        persisted["cards"][0]["settings"]["dflash"] = True
        llm_registry.REGISTRY_FILE.write_text(json.dumps(persisted), encoding="utf-8")
        self.assertNotIn("dflash", llm_registry.read_llm_registry()["cards"][0]["settings"])

    def test_card_settings_reject_off_memory_guard(self) -> None:
        endpoint = llm_registry.create_llm_endpoint({"provider": "openai", "baseUrl": "https://example.invalid/v1"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "model"})
        with self.assertRaises(Exception):
            llm_registry.update_llm_card(card["id"], {"settings": {"memoryGuard": "off"}})

    def test_external_card_removal_never_deletes_source_files(self) -> None:
        source = Path(self.temporary.name) / "external"
        source.mkdir()
        marker = source / "weights.safetensors"
        marker.write_bytes(b"data")
        endpoint = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "external-model",
                                             "source": "external", "localMetadata": {"path": str(source)}})
        result = llm_registry.delete_llm_card(card["id"])
        self.assertTrue(marker.is_file())
        self.assertEqual(result["action"], "unregistered")
        self.assertFalse(result["modelFilesDeleted"])

    def test_managed_target_removes_unshared_mtp_asset(self) -> None:
        managed_root = Path(self.temporary.name) / "managed-root"
        model = managed_root / "models" / "target"
        model.mkdir(parents=True)
        (model / "weights.safetensors").write_bytes(b"target")
        mtp_root = managed_root / ".runtime-assets" / "mtp" / "asset"
        mtp_root.mkdir(parents=True)
        (mtp_root / "partial").write_bytes(b"partial")
        endpoint = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "target", "source": "managed",
            "localMetadata": {"path": str(model), "repoId": "mlx-community/gemma-4-31b-it-nvfp4",
                              "revision": "a0a935b105621b98907915fa12f05348bb9c3c24"}})
        status = {"diskBytes": 7}
        with (patch("server.modules.constants.LOCAL_LLM_ROOT", managed_root),
              patch("server.modules.export_service.active_draft_job", return_value=False),
              patch("server.modules.export_service.active_export_job", return_value=False),
              patch("server.modules.llm_model_tests.llm_model_test_active", return_value=False),
              patch("server.modules.mtp_assets.mtp_download_active", return_value=False),
              patch("server.modules.mtp_assets.mtp_asset_status", return_value=status),
              patch("server.modules.mtp_assets.remove_mtp_asset") as remove,
              patch("server.modules.local_llm_runtime.unload_local_llm"),
              patch("server.modules.local_llm_storage.rebuild_local_llm_discovery")):
            result = llm_registry.delete_llm_card(card["id"])
        remove.assert_called_once()
        self.assertTrue(result["mtpDeleted"])
        self.assertFalse(model.exists())

    def test_managed_card_rejects_path_outside_fixed_root(self) -> None:
        source = Path(self.temporary.name) / "outside"
        source.mkdir()
        endpoint = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "managed-model",
                                             "source": "managed", "localMetadata": {"path": str(source)}})
        with (
            patch("server.modules.constants.LOCAL_LLM_ROOT", Path(self.temporary.name) / "managed-root"),
            patch("server.modules.export_service.active_draft_job", return_value=None),
            patch("server.modules.export_service.active_export_job", return_value=None),
        ):
            with self.assertRaises(Exception):
                llm_registry.delete_llm_card(card["id"])
        self.assertTrue(source.is_dir())

    def test_managed_card_rejects_symlink_inside_fixed_root(self) -> None:
        managed_root = Path(self.temporary.name) / "managed-root"
        models = managed_root / "models"
        target = Path(self.temporary.name) / "target"
        models.mkdir(parents=True)
        target.mkdir()
        link = models / "linked-model"
        link.symlink_to(target, target_is_directory=True)
        endpoint = llm_registry.create_llm_endpoint({"provider": "scena-local"})
        card = llm_registry.create_llm_card({"endpointId": endpoint["id"], "modelId": "linked-model",
                                             "source": "managed", "localMetadata": {"path": str(link)}})
        with (
            patch("server.modules.constants.LOCAL_LLM_ROOT", managed_root),
            patch("server.modules.export_service.active_draft_job", return_value=None),
            patch("server.modules.export_service.active_export_job", return_value=None),
        ):
            with self.assertRaises(Exception):
                llm_registry.delete_llm_card(card["id"])
        self.assertTrue(target.is_dir())


if __name__ == "__main__":
    unittest.main()

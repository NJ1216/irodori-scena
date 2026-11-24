from __future__ import annotations

import hashlib
import threading
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server import application  # noqa: F401
from server.modules import lora_routes  # noqa: F401
from server.modules import lora_assets, lora_asset_lifecycle, project_repository
from server.modules.lora_storage import read_record
from server.registry import deps
import test_lora_assets as asset_tests


def file_hashes(directory: Path) -> dict[str, str]:
    return {str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in directory.rglob("*") if path.is_file()}


class LoraAssetLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = asset_tests.LoraAssetTests()
        self.fixture.setUp()
        self.record = lora_assets.import_adapter(str(self.fixture.source), "管理用LoRA")
        self.identifier = self.record["id"]
        self.project = {"id": "qa", "characters": [], "scenes": []}
        self.globals = []
        self.patches = [patch.object(project_repository, "read_project", return_value=self.project),
                        patch.object(project_repository, "read_global_characters", return_value=self.globals)]
        for item in self.patches:
            item.start()
        self.client = TestClient(deps.app)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.fixture.tearDown()

    def test_archive_and_restore_are_idempotent_and_never_delete_adapter_or_source(self):
        source_before = file_hashes(self.fixture.source)
        descriptor_before = lora_assets.resolve_lora_asset(self.record)
        directory = Path(descriptor_before["path"])
        bytes_before = {name: (directory / name).read_bytes() for name in ("adapter_config.json", "adapter_model.safetensors")}
        archived = lora_asset_lifecycle.archive_adapter(self.identifier)
        self.assertTrue(archived["archived"])
        self.assertEqual(lora_assets.list_adapters(), [])
        self.assertEqual(lora_assets.list_adapters(archived=True), [archived])
        self.assertEqual(lora_assets.list_adapters(include_archived=True), [archived])
        self.assertEqual(lora_asset_lifecycle.archive_adapter(self.identifier), archived)
        # References in saved projects outside the checked scope still resolve.
        self.assertEqual(lora_assets.resolve_lora_asset(self.record), descriptor_before)
        restored = lora_asset_lifecycle.restore_adapter(self.identifier)
        self.assertFalse(restored["archived"])
        self.assertEqual(lora_asset_lifecycle.restore_adapter(self.identifier), restored)
        self.assertEqual(lora_assets.list_adapters(), [restored])
        self.assertEqual(file_hashes(self.fixture.source), source_before)
        self.assertEqual({name: (directory / name).read_bytes() for name in bytes_before}, bytes_before)

    def test_project_and_global_cast_references_block_even_when_disabled(self):
        for scope in ("project", "global"):
            for enabled in (True, False):
                with self.subTest(scope=scope, enabled=enabled):
                    self.project["characters"] = []
                    self.globals.clear()
                    character = {"id": "cast", "name": "使用中", "lora": {**self.record, "enabled": enabled}, "scope": scope}
                    (self.globals if scope == "global" else self.project["characters"]).append(character)
                    with self.assertRaises(HTTPException) as caught:
                        lora_asset_lifecycle.archive_adapter(self.identifier)
                    self.assertEqual(caught.exception.status_code, 409)
                    usage = caught.exception.detail["usage"]
                    self.assertEqual(usage["casts"], [{"id": "cast", "name": "使用中", "scope": scope}])
                    self.assertFalse(read_record("adapters", self.identifier).get("archived", False))

    def test_current_take_reference_blocks_even_after_cast_was_cleared(self):
        self.project["scenes"] = [{"lines": [{"id": "line", "characterId": "cast", "takes": [{"id": "take", "lora": {**self.record, "enabled": False}}]}]}]
        usage = lora_asset_lifecycle.adapter_usage(self.identifier)
        self.assertEqual(usage["takeCount"], 1)
        self.assertEqual(usage["takes"], [{"lineId": "line", "takeId": "take", "characterId": "cast"}])
        self.assertFalse(usage["otherSavedProjectsChecked"])
        with self.assertRaises(HTTPException) as caught:
            lora_asset_lifecycle.archive_adapter(self.identifier)
        self.assertEqual(caught.exception.detail["code"], "lora_asset_in_use")

    def test_archive_can_hide_missing_config_but_restore_keeps_it_archived(self):
        directory = Path(lora_assets.resolve_lora_asset(self.record)["path"])
        (directory / "adapter_config.json").unlink()
        lora_asset_lifecycle.archive_adapter(self.identifier)
        with self.assertRaises(HTTPException):
            lora_asset_lifecycle.restore_adapter(self.identifier)
        self.assertTrue(read_record("adapters", self.identifier)["archived"])
        self.assertTrue((directory / "adapter_model.safetensors").exists())

    def test_failed_import_missing_config_never_leaves_registration(self):
        before = {path.name for path in (self.fixture.root / "managed/lora/adapters").iterdir()}
        (self.fixture.source / "adapter_config.json").unlink()
        with self.assertRaises(HTTPException):
            lora_assets.import_adapter(str(self.fixture.source), "broken")
        self.assertEqual({path.name for path in (self.fixture.root / "managed/lora/adapters").iterdir()}, before)

    def test_training_or_runtime_busy_does_not_change_registration(self):
        with patch.object(lora_asset_lifecycle, "require_runtime_available", side_effect=HTTPException(409, "busy")):
            with self.assertRaises(HTTPException):
                lora_asset_lifecycle.archive_adapter(self.identifier)
        with patch.object(lora_asset_lifecycle, "LOCK") as lock:
            lock.acquire.return_value = False
            with self.assertRaises(HTTPException):
                lora_asset_lifecycle.restore_adapter(self.identifier)
            lock.release.assert_not_called()
        self.assertFalse(read_record("adapters", self.identifier).get("archived", False))

    def test_other_runtime_thread_admission_blocks_archive_without_mutation(self):
        acquired = threading.Event()
        finish = threading.Event()
        def runtime_request():
            with lora_asset_lifecycle.LOCK:
                acquired.set()
                finish.wait(2)
        worker = threading.Thread(target=runtime_request)
        worker.start()
        try:
            self.assertTrue(acquired.wait(1))
            with self.assertRaises(HTTPException) as caught:
                lora_asset_lifecycle.archive_adapter(self.identifier)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertFalse(read_record("adapters", self.identifier).get("archived", False))
        finally:
            finish.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_http_archive_lists_lookup_and_restore_contract(self):
        url = f"/api/lora/adapters/{self.identifier}"
        response = self.client.get(url + "/usage")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["scope"], "current_project_and_global_casts")
        response = self.client.post(url + "/archive")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["archived"])
        self.assertEqual(self.client.get("/api/lora/adapters").json(), [])
        self.assertEqual(len(self.client.get("/api/lora/adapters/archived").json()), 1)
        self.assertEqual(len(self.client.get("/api/lora/adapters?includeArchived=true").json()), 1)
        response = self.client.post(url + "/restore")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["archived"])
        self.assertEqual(self.client.post("/api/lora/adapters/invalid/archive").status_code, 422)

    def test_metadata_edit_preserves_weights_references_and_archival_state(self):
        directory = Path(lora_assets.resolve_lora_asset(self.record)["path"])
        before = {name: (directory / name).read_bytes() for name in ("adapter_config.json", "adapter_model.safetensors")}
        response = self.client.patch(f"/api/lora/adapters/{self.identifier}", json={"name": "新しい名前", "memo": "メモ"})
        self.assertEqual(response.status_code, 200, response.text)
        edited = response.json()
        self.assertEqual(edited["memo"], "メモ")
        self.assertEqual(edited["adapterHash"], self.record["adapterHash"])
        for name, data in before.items():
            self.assertEqual((directory / name).read_bytes(), data)
        self.assertEqual(self.client.patch(f"/api/lora/adapters/{self.identifier}", json={"name": " ", "memo": ""}).status_code, 422)
        self.assertEqual(read_record("adapters", self.identifier)["name"], "新しい名前")

    def test_continuation_freezes_only_validated_adapter_and_rejects_archived_or_tampered_source(self):
        from server.modules.lora_continuation import freeze_adapter
        runtime = {"checkpoint": str(self.fixture.base)}
        job = self.fixture.root / "continuation"
        job.mkdir()
        source = Path(lora_assets.resolve_lora_asset(self.record)["path"])
        before = file_hashes(source)
        descriptor = freeze_adapter(self.identifier, job, runtime)
        self.assertEqual(descriptor["assetId"], self.identifier)
        self.assertEqual(file_hashes(source), before)
        self.assertEqual({p.name for p in (job / "source-adapter").iterdir()}, {"adapter_config.json", "adapter_model.safetensors"})
        lora_asset_lifecycle.archive_adapter(self.identifier)
        with self.assertRaises(HTTPException):
            freeze_adapter(self.identifier, job, runtime)
        lora_asset_lifecycle.restore_adapter(self.identifier)
        (source / "adapter_model.safetensors").write_bytes(b"tampered")
        with self.assertRaises(HTTPException):
            freeze_adapter(self.identifier, job, runtime)

    def test_permanent_delete_removes_owned_weights_and_related_job_copies_only(self):
        from server.modules.lora_storage import owned_path, write_json
        source_before = file_hashes(self.fixture.source)
        directory = owned_path("adapters", self.identifier)
        job = owned_path("jobs", "a" * 32)
        write_json(job / "record.json", {"id": job.name, "adapterId": self.identifier, "sourceAdapterId": self.identifier, "status": "completed"})
        for name in ("training/checkpoint_final/adapter_model.safetensors", "source-adapter/adapter_model.safetensors", "input.wav"):
            path = job / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"owned")
        response = self.client.delete(f"/api/lora/adapters/{self.identifier}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["deleted"])
        self.assertFalse(directory.exists())
        self.assertFalse((job / "training").exists())
        self.assertFalse((job / "source-adapter").exists())
        self.assertTrue((job / "input.wav").exists())
        self.assertEqual(file_hashes(self.fixture.source), source_before)
        self.assertEqual(self.client.get("/api/lora/adapters?includeArchived=true").json(), [])
        self.assertEqual(self.client.post(f"/api/lora/adapters/{self.identifier}/restore").status_code, 404)

    def test_permanent_delete_refuses_cast_take_and_busy_runtime_without_changing_bytes(self):
        from server.modules.lora_storage import owned_path
        directory = owned_path("adapters", self.identifier)
        before = file_hashes(directory)
        reference = {"loraMix": {"entries": [{"assetId": self.identifier, "weight": 1000}]}}
        self.globals.append({"id": "global", "name": "global", **reference})
        self.assertEqual(self.client.delete(f"/api/lora/adapters/{self.identifier}").status_code, 409)
        self.globals.clear()
        self.project["scenes"] = [{"lines": [{"id": "line", "takes": [{"id": "take", **reference}]}]}]
        self.assertEqual(self.client.delete(f"/api/lora/adapters/{self.identifier}").status_code, 409)
        self.project["scenes"] = []
        with patch.object(lora_asset_lifecycle, "require_runtime_available", side_effect=HTTPException(409, "busy")):
            self.assertEqual(self.client.delete(f"/api/lora/adapters/{self.identifier}").status_code, 409)
        self.assertEqual(file_hashes(directory), before)

    def test_permanent_delete_rejects_job_symlink_without_deleting_external_data(self):
        from server.modules.lora_storage import owned_path, write_json
        job = owned_path("jobs", "b" * 32)
        write_json(job / "record.json", {"adapterId": self.identifier})
        (job / "training").symlink_to(self.fixture.source, target_is_directory=True)
        before = file_hashes(self.fixture.source)
        self.assertEqual(self.client.delete(f"/api/lora/adapters/{self.identifier}").status_code, 409)
        self.assertEqual(file_hashes(self.fixture.source), before)
        self.assertTrue(owned_path("adapters", self.identifier).is_dir())

    def test_permanent_delete_io_failure_retains_registration(self):
        from server.modules.lora_storage import owned_path
        directory = owned_path("adapters", self.identifier)
        before = file_hashes(directory)
        with patch.object(lora_asset_lifecycle, "delete_adapter_files", side_effect=OSError("denied")):
            self.assertEqual(self.client.delete(f"/api/lora/adapters/{self.identifier}").status_code, 409)
        self.assertEqual(file_hashes(directory), before)

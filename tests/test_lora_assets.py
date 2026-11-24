from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from fastapi import HTTPException
from server.modules import constants, lora_assets
from server.modules.lora_storage import digest
from server.modules.lora_validation import TARGET_PATTERN
from test_lora_validation import tensor_file


class LoraAssetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.base = self.root / "base.safetensors"
        tensor_file(self.base, {"blocks.0.attention.wq.weight": np.zeros((3, 4)), "duration_predictor.weight": np.zeros((2, 3))})
        config = {"peft_type": "LORA", "r": 2, "lora_alpha": 4, "bias": "none",
                  "target_modules": TARGET_PATTERN, "modules_to_save": ["duration_predictor"]}
        (self.source / "adapter_config.json").write_text(json.dumps(config))
        tensor_file(self.source / "adapter_model.safetensors", {
            "base_model.model.blocks.0.attention.wq.lora_A.weight": np.ones((2, 4)),
            "base_model.model.blocks.0.attention.wq.lora_B.weight": np.ones((3, 2)),
            "base_model.model.duration_predictor.weight": np.ones((2, 3))})
        self.patches = [patch.object(constants, "TTS_ASSETS_ROOT", self.root / "managed"),
                        patch.object(lora_assets, "base_checkpoint", return_value=self.base),
                        patch.object(lora_assets, "BASE_SHA256", digest(self.base))]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_import_copies_only_safe_adapter_files_and_source_edit_does_not_change_asset(self):
        (self.source / "trainer_state.pt").write_bytes(b"untrusted pickle must not be loaded")
        record = lora_assets.import_adapter(str(self.source), "management name", "memo")
        descriptor = lora_assets.resolve_lora_asset(record)
        self.assertEqual(set(p.name for p in Path(descriptor["path"]).iterdir()),
                         {"adapter_config.json", "adapter_model.safetensors", "record.json"})
        (self.source / "adapter_config.json").write_text("changed source")
        self.assertEqual(lora_assets.resolve_lora_asset(record), descriptor)

    def test_modified_managed_config_missing_asset_and_identity_mismatch_are_explicit_errors(self):
        record = lora_assets.import_adapter(str(self.source), "name")
        for changed in ({**record, "adapterHash": "wrong"}, {**record, "assetId": "b" * 32}):
            with self.assertRaises(HTTPException) as caught:
                lora_assets.resolve_lora_asset(changed)
            self.assertEqual(caught.exception.status_code, 409)
        path = Path(lora_assets.resolve_lora_asset(record)["path"])
        (path / "adapter_config.json").write_text("{}")
        with self.assertRaises(HTTPException):
            lora_assets.resolve_lora_asset(record)

    def test_import_failure_removes_partial_asset(self):
        with patch.object(lora_assets, "base_checkpoint", side_effect=HTTPException(409, "missing base")):
            with self.assertRaises(HTTPException):
                lora_assets.import_adapter(str(self.source), "name")
        self.assertEqual(lora_assets.list_adapters(), [])
        self.assertEqual(list((self.root / "managed/lora/adapters").iterdir()), [])

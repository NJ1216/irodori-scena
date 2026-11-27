from __future__ import annotations
import scena_test_isolation  # noqa: F401
import json
import struct
from pathlib import Path
import tempfile
import unittest
import numpy as np
from server.modules.lora_validation import TARGET_PATTERN, validate_adapter


def tensor_file(path: Path, tensors: dict):
    header, payload = {}, b""
    for name, value in tensors.items():
        data = np.asarray(value, dtype="<f4").tobytes()
        header[name] = {"dtype": "F32", "shape": list(value.shape), "data_offsets": [len(payload), len(payload) + len(data)]}
        payload += data
    raw = json.dumps(header).encode()
    path.write_bytes(struct.pack("<Q", len(raw)) + raw + payload)


class LoraValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "base.safetensors"
        tensor_file(self.base, {"blocks.0.attention.wq.weight": np.zeros((3, 4)), "duration_predictor.weight": np.zeros((2, 3))})
        self.config = {"peft_type": "LORA", "r": 2, "lora_alpha": 4, "bias": "none",
                       "target_modules": TARGET_PATTERN, "modules_to_save": ["duration_predictor"]}
        self.tensors = {"base_model.model.blocks.0.attention.wq.lora_A.weight": np.ones((2, 4)),
                        "base_model.model.blocks.0.attention.wq.lora_B.weight": np.ones((3, 2)),
                        "base_model.model.duration_predictor.weight": np.ones((2, 3))}
        self.write()

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        (self.root / "adapter_config.json").write_text(json.dumps(self.config))
        tensor_file(self.root / "adapter_model.safetensors", self.tensors)

    def test_accepts_complete_tested_schema(self):
        self.assertEqual(validate_adapter(self.root, self.base)["tensorCount"], 3)

    def test_unknown_missing_nonfinite_and_wrong_shape_rejected(self):
        original = dict(self.tensors)
        for change in ("unknown", "missing", "nan", "single-inf", "shape"):
            self.tensors = dict(original)
            if change == "unknown":
                self.tensors["evil.weight"] = np.ones((1,))
            elif change == "missing":
                self.tensors.pop(next(iter(self.tensors)))
            elif change == "nan":
                self.tensors[next(iter(self.tensors))] = np.full((2, 4), np.nan)
            elif change == "single-inf":
                values = np.ones((3, 2))
                values[2, 1] = -np.inf
                self.tensors["base_model.model.blocks.0.attention.wq.lora_B.weight"] = values
            else:
                self.tensors[next(iter(self.tensors))] = np.ones((4, 2))
            self.write()
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_adapter(self.root, self.base)

    def test_unsupported_peft_and_truncation_rejected(self):
        self.config["use_dora"] = True
        self.write()
        with self.assertRaises(ValueError):
            validate_adapter(self.root, self.base)
        self.config.pop("use_dora")
        self.write()
        path = self.root / "adapter_model.safetensors"
        path.write_bytes(path.read_bytes()[:-4])
        with self.assertRaises(ValueError):
            validate_adapter(self.root, self.base)

    def test_nondictionary_tensor_header_is_rejected(self):
        path = self.root / "adapter_model.safetensors"
        for value in (None, [], "bad", 3):
            tensor_file(path, self.tensors)
            raw = path.read_bytes()
            length = struct.unpack("<Q", raw[:8])[0]
            header = json.loads(raw[8:8 + length])
            header[next(iter(header))] = value
            encoded = json.dumps(header).encode()
            path.write_bytes(struct.pack("<Q", len(encoded)) + encoded + raw[8 + length:])
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_adapter(self.root, self.base)

from __future__ import annotations

import struct
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules.llama_cpp_context import GgufMetadataError, read_gguf_context_limit, select_context_size
from server.modules import llm_registry


def _text(value: str) -> bytes:
    encoded = value.encode()
    return struct.pack("<Q", len(encoded)) + encoded


def gguf(entries: list[tuple[str, int, bytes]]) -> bytes:
    metadata = b"".join(_text(key) + struct.pack("<I", kind) + value for key, kind, value in entries)
    return b"GGUF" + struct.pack("<IQQ", 3, 0, len(entries)) + metadata


class LlamaCppContextTests(unittest.TestCase):
    def test_reads_architecture_context_and_skips_known_sibling_types(self):
        data = gguf([
            ("general.name", 8, _text("fixture")),
            ("general.file_type", 4, struct.pack("<I", 15)),
            ("gemma3.context_length", 10, struct.pack("<Q", 131072)),
            ("general.architecture", 8, _text("gemma3")),
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.gguf"
            path.write_bytes(data)
            self.assertEqual(read_gguf_context_limit(path), 131072)

    def test_rejects_truncated_and_unknown_metadata_types(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.gguf"
            path.write_bytes(gguf([("general.architecture", 8, _text("gemma3"))])[:-1])
            with self.assertRaises(GgufMetadataError):
                read_gguf_context_limit(path)
            path.write_bytes(gguf([("unknown", 99, b"")]))
            with self.assertRaises(GgufMetadataError):
                read_gguf_context_limit(path)

    def test_applies_model_manual_and_memory_limits(self):
        metadata = {"files": ["first.gguf", "second.gguf"], "diskBytes": 4 * 1024**3}
        with patch("server.modules.llama_cpp_context.read_gguf_context_limit", return_value=131072):
            self.assertEqual(select_context_size(metadata, "cuda", available_bytes=12 * 1024**3), 32768)
            self.assertEqual(select_context_size(metadata, "cpu", 16000, available_bytes=12 * 1024**3), 8192)
            self.assertEqual(select_context_size(metadata, "cpu", available_bytes=9 * 1024**3), 16384)

    def test_unknown_capacity_uses_8k_and_insufficient_memory_is_specific(self):
        with patch("server.modules.llama_cpp_context.read_gguf_context_limit", return_value=32768):
            self.assertEqual(select_context_size({}, "cpu", available_bytes=None), 8192)
            with self.assertRaisesRegex(MemoryError, "Context 8,192"):
                select_context_size({"diskBytes": 8 * 1024**3}, "cpu", available_bytes=10 * 1024**3)

    def test_registry_migration_backfills_existing_gguf_without_redownload(self):
        with tempfile.TemporaryDirectory() as directory:
            registry_file = Path(directory) / "llm-registry.json"
            registry_file.write_text(json.dumps({
                "version": 4, "defaultCardId": "card", "endpoints": [{"id": "endpoint"}],
                "cards": [{"id": "card", "endpointId": "endpoint", "localMetadata": {
                    "format": "GGUF", "files": ["model.gguf"],
                }}],
            }), encoding="utf-8")
            with patch.object(llm_registry, "REGISTRY_FILE", registry_file), \
                    patch("server.modules.llama_cpp_context.model_context_limit", return_value=131072), \
                    patch.object(llm_registry, "migrate_bindings"):
                migrated = llm_registry.read_llm_registry()
            self.assertEqual(migrated["version"], llm_registry.REGISTRY_VERSION)
            self.assertEqual(migrated["cards"][0]["localMetadata"]["modelContextLimit"], 131072)

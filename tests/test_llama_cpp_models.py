from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import server.app  # noqa: F401
from fastapi import HTTPException
from server.modules.llama_cpp_models import scan_gguf_folder


class LlamaCppModelTests(unittest.TestCase):
    def test_groups_complete_shards_and_reports_missing_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "model-Q4-00001-of-00002.gguf").write_bytes(b"a")
            (root / "model-Q4-00002-of-00002.gguf").write_bytes(b"bb")
            (root / "broken-00001-of-00002.gguf").write_bytes(b"c")
            result = scan_gguf_folder(str(root))
        self.assertEqual(result["models"][0]["shardCount"], 2)
        self.assertEqual(result["models"][0]["diskBytes"], 3)
        self.assertEqual(result["incomplete"][0]["foundShards"], 1)

    def test_ignores_symlinks_and_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "model.gguf"
            source.write_bytes(b"original")
            (root / "linked.gguf").symlink_to(source)
            result = scan_gguf_folder(str(root))
            self.assertEqual(len(result["models"]), 1)
            self.assertEqual(source.read_bytes(), b"original")

    def test_rejects_symlink_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(HTTPException):
                scan_gguf_folder(str(link))

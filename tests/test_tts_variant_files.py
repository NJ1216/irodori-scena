from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.modules.tts_variant_files import remove_variant_files


class TtsVariantFileTests(unittest.TestCase):
    def test_deleting_shared_quantized_variant_keeps_tokenizer_and_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shared = root / "models" / "revision"
            first = shared / "int8-weight-only" / "model.safetensors"
            sibling = shared / "int8-dynamic" / "model.safetensors"
            tokenizer = shared / "tokenizer" / "tokenizer.json"
            for path in (first, sibling, tokenizer):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"asset")
            variants = [
                {"id": "w8a16", "path": str(shared), "checkpointFile": "int8-weight-only/model.safetensors"},
                {"id": "w8a8", "path": str(shared), "checkpointFile": "int8-dynamic/model.safetensors"},
            ]
            remove_variant_files(variants[0], variants, root / "models")
            self.assertFalse(first.exists())
            self.assertTrue(sibling.is_file())
            self.assertTrue(tokenizer.is_file())


if __name__ == "__main__":
    unittest.main()

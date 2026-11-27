from __future__ import annotations

import scena_test_isolation  # noqa: F401
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.irodori_runtime_layout import prepare_runtime_checkpoint


class IrodoriRuntimeLayoutTests(unittest.TestCase):
    def test_windows_nested_checkpoint_uses_unprivileged_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "model" / "float8-dynamic" / "model.safetensors"
            tokenizer = root / "model" / "tokenizer"
            checkpoint.parent.mkdir(parents=True)
            tokenizer.mkdir()
            checkpoint.write_bytes(b"quantized-model")
            (tokenizer / "tokenizer.json").write_text("{}", encoding="utf-8")
            (tokenizer / "tokenizer_config.json").write_text("{}", encoding="utf-8")

            with patch("server.irodori_runtime_layout.sys.platform", "win32"), patch.object(
                Path, "symlink_to", side_effect=AssertionError("Windows staging must not require symlink privileges")
            ):
                staged = prepare_runtime_checkpoint(checkpoint, tokenizer)
            try:
                self.assertTrue(staged.path.samefile(checkpoint))
                self.assertEqual((staged.path.parent / "tokenizer" / "tokenizer.json").read_text(), "{}")
            finally:
                temporary_root = staged.temporary_root
                staged.cleanup()
            self.assertIsNotNone(temporary_root)
            self.assertFalse(temporary_root.exists())

    def test_already_adjacent_tokenizer_needs_no_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "model.safetensors"
            tokenizer = root / "tokenizer"
            checkpoint.write_bytes(b"model")
            tokenizer.mkdir()

            staged = prepare_runtime_checkpoint(checkpoint, tokenizer)

            self.assertEqual(staged.path, checkpoint)
            self.assertIsNone(staged.temporary_root)


if __name__ == "__main__":
    unittest.main()

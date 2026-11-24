from __future__ import annotations

import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import rhubarb_runtime as runtime

from server.modules.rhubarb_runtime import _safe_extract, _verify_architecture


class RhubarbRuntimeTests(unittest.TestCase):
    def test_download_reports_bytes_and_bounds_final_block(self):
        job = {"state": "downloading", "totalBytes": 100}
        with patch.object(runtime, "INSTALL_JOB", job):
            runtime._download_progress(2, 20, 100)
            self.assertEqual(job["downloadedBytes"], 40)
            runtime._download_progress(6, 20, 100)
            self.assertEqual(job["downloadedBytes"], 100)
            runtime._download_progress(2, 20, -1)
            self.assertEqual(job["totalBytes"], 100)

    def test_unknown_download_size_and_cancellation(self):
        job = {"state": "downloading"}
        with patch.object(runtime, "INSTALL_JOB", job):
            runtime._download_progress(2, 20, -1)
            self.assertEqual(job["downloadedBytes"], 40)
            self.assertEqual(job["totalBytes"], 0)
            job["cancelRequested"] = True
            with self.assertRaisesRegex(RuntimeError, "キャンセル"):
                runtime._download_progress(3, 20, -1)
            self.assertEqual(job["downloadedBytes"], 40)

    def test_accepts_arm64_macho_and_x64_pe_headers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            macho = root / "rhubarb"
            macho.write_bytes(b"\xcf\xfa\xed\xfe" + struct.pack("<I", 0x0100000C))
            _verify_architecture(macho, "darwin-arm64")
            pe = bytearray(256)
            pe[:2] = b"MZ"
            pe[0x3C:0x40] = struct.pack("<I", 128)
            pe[128:132] = b"PE\0\0"
            pe[132:134] = struct.pack("<H", 0x8664)
            windows = root / "rhubarb.exe"
            windows.write_bytes(pe)
            _verify_architecture(windows, "windows-x64")

    def test_extract_requires_exact_safe_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "runtime.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("rhubarb/rhubarb", b"binary")
            _safe_extract(archive, root / "out", ["rhubarb/rhubarb"])
            with self.assertRaises(RuntimeError):
                _safe_extract(archive, root / "other", ["rhubarb/LICENSE.md"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import hashlib
import json
import unittest
import zipfile
from pathlib import Path

from tools.release.package_rhubarb import build


class PackageRhubarbTests(unittest.TestCase):
    def test_japanese_worker_assets_are_pinned_and_unlisted_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'rhubarb'
            (root / 'res/sphinx').mkdir(parents=True)
            (root / 'rhubarb').write_bytes(b'binary')
            (root / 'LICENSE.md').write_text('MIT')
            addon = Path(temporary) / 'addon'
            addon.mkdir()
            (addon / 'worker').write_bytes(b'worker')
            (addon / 'private.log').write_text('not shipped')
            manifest = {'files': {'worker': hashlib.sha256(b'worker').hexdigest()},
                        'analysisVersion': 'v3', 'publicationReview': 'pending', 'executable': 'worker'}
            (addon / 'manifest.json').write_text(json.dumps(manifest))
            output = Path(temporary) / 'review.zip'
            result = build(root, output, 'darwin-arm64', 'commit', addon)
            self.assertEqual(result['japaneseAddon']['analysisVersion'], 'v3')
            with zipfile.ZipFile(output) as archive:
                self.assertIn('rhubarb/japanese-lipsync/worker', archive.namelist())
                self.assertNotIn('rhubarb/japanese-lipsync/private.log', archive.namelist())
                self.assertTrue(archive.getinfo('rhubarb/japanese-lipsync/worker').external_attr >> 16 & 0o100)
            (addon / 'worker').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                build(root, output, 'darwin-arm64', 'commit', addon)

    def test_packages_only_executable_license_resources_and_build_info(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "input"
            (root / "res" / "sphinx").mkdir(parents=True)
            (root / "rhubarb").write_bytes(b"binary")
            (root / "LICENSE.md").write_text("MIT")
            (root / "README.md").write_text("not shipped")
            (root / "res" / "sphinx" / "model").write_bytes(b"model")
            first, second = Path(temporary) / "first.zip", Path(temporary) / "second.zip"
            result = build(root, first, "darwin-arm64", "commit")
            build(root, second, "darwin-arm64", "commit")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(set(result["files"]), {"rhubarb/BUILD-INFO.json", "rhubarb/LICENSE.md", "rhubarb/res/sphinx/model", "rhubarb/rhubarb"})
            with zipfile.ZipFile(first) as archive:
                self.assertNotIn("rhubarb/README.md", archive.namelist())


if __name__ == "__main__":
    unittest.main()

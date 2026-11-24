"""Mac bundle cleanup follows successful auditing and preserves the DMG."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "tools/inspect-tauri-bundle.sh"


@unittest.skipUnless(os.name == "posix", "Mac release inspection requires POSIX shell and executables")
class MacBuildCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "tools").mkdir()
        self.script = self.root / "tools/inspect-tauri-bundle.sh"
        shutil.copyfile(SCRIPT, self.script)
        bundle = self.root / "src-tauri/target/aarch64-apple-darwin/release/bundle"
        self.app = bundle / "macos/irodori SCENA.app"
        resources = self.app / "Contents/Resources"
        for relative in ("omlx-bootstrap/requirements.txt", "ja.lproj/InfoPlist.strings",
                         "scena-api-runtime/_internal/server/catalogs/rhubarb-runtime.json",
                         "scena-api-runtime/_internal/server/mlx_irodori_worker.py"):
            path = resources / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
        for path in (resources / "scena-api-runtime/scena-api", self.app / "Contents/MacOS/irodori-scena"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture")
            path.chmod(0o755)
        self.dmg = bundle / "dmg/irodori SCENA_26.9.29_aarch64.dmg"
        self.distribution = self.dmg.with_name("irodori SCENA_26.9.29_AppleSilicon.dmg")
        self.dmg.parent.mkdir()
        self.dmg.write_bytes(b"verified DMG fixture")
        stubs = self.root / "stubs"
        stubs.mkdir()
        for name, body in {"file": "echo arm64", "codesign": 'exit "$AUDIT_EXIT"',
                           "uv": "exit 0", "du": "exit 0", "node": "echo 26.9.29",
                           "hdiutil": 'exit "$DMG_EXIT"', "ps": 'printf "%s" "$RUNNING_APP"; exit "$PROCESS_EXIT"'}.items():
            path = stubs / name
            path.write_text("#!/bin/sh\n" + body + "\n")
            path.chmod(0o755)
        self.env = {**os.environ, "PATH": str(stubs) + os.pathsep + os.environ["PATH"],
                    "AUDIT_EXIT": "0", "DMG_EXIT": "0", "RUNNING_APP": "", "PROCESS_EXIT": "0"}

    def run_inspection(self):
        return subprocess.run(["bash", str(self.script)], env=self.env, capture_output=True, check=False)

    def test_success_removes_only_intermediate_app_and_keeps_dmg(self):
        unrelated = self.app.parent / "Other.app"
        unrelated.mkdir()
        result = self.run_inspection()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.app.exists())
        self.assertTrue(unrelated.exists())
        self.assertFalse(self.dmg.exists())
        self.assertEqual(self.distribution.read_bytes(), b"verified DMG fixture")

    def test_existing_distribution_is_not_overwritten(self):
        self.distribution.write_bytes(b"existing distribution")
        self.assertNotEqual(self.run_inspection().returncode, 0)
        self.assertTrue(self.app.exists())
        self.assertEqual(self.dmg.read_bytes(), b"verified DMG fixture")
        self.assertEqual(self.distribution.read_bytes(), b"existing distribution")

    def test_failed_rename_preserves_app_and_original_dmg(self):
        command = self.root / "stubs/mv"
        command.write_text("#!/bin/sh\nexit 1\n")
        command.chmod(0o755)
        self.assertNotEqual(self.run_inspection().returncode, 0)
        self.assertTrue(self.app.exists())
        self.assertEqual(self.dmg.read_bytes(), b"verified DMG fixture")
        self.assertFalse(self.distribution.exists())

    def test_failed_audit_or_dmg_verification_preserves_app(self):
        for variable in ("AUDIT_EXIT", "DMG_EXIT", "PROCESS_EXIT"):
            with self.subTest(variable=variable):
                self.env[variable] = "1"
                self.assertNotEqual(self.run_inspection().returncode, 0)
                self.assertTrue(self.app.exists())
                self.assertTrue(self.dmg.exists())
                self.env[variable] = "0"

    def test_missing_current_dmg_preserves_app(self):
        self.dmg.unlink()
        self.assertNotEqual(self.run_inspection().returncode, 0)
        self.assertTrue(self.app.exists())

    def test_running_app_is_retained(self):
        self.env["RUNNING_APP"] = str(self.app / "Contents/MacOS/irodori-scena")
        self.assertNotEqual(self.run_inspection().returncode, 0)
        self.assertTrue(self.app.exists())
        self.assertTrue(self.dmg.exists())

    def test_symlinked_app_is_retained(self):
        original = self.app.parent / "Original.app"
        self.app.rename(original)
        self.app.symlink_to(original, target_is_directory=True)
        self.assertNotEqual(self.run_inspection().returncode, 0)
        self.assertTrue(self.app.is_symlink())
        self.assertTrue(original.exists())

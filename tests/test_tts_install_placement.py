import scena_test_isolation  # noqa: F401
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.modules.tts_install_placement import (
    engine_environment_path,
    place_windows_directory,
    retry_windows_file_operation,
)


class TtsInstallPlacementTests(unittest.TestCase):
    def test_darwin_environment_path_preserves_staging_and_existing_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging, target = root / "staging", root / "target"
            target.mkdir()
            (target / "keep").write_text("complete", encoding="utf-8")

            self.assertEqual(engine_environment_path(staging, target, "darwin"), staging)
            self.assertTrue((target / "keep").is_file())

    def test_windows_environment_is_built_at_final_path_and_stale_attempt_is_recovered(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staging, target = root / "staging", root / "environments/runtime"
            target.mkdir(parents=True)
            (target / "partial").write_text("incomplete", encoding="utf-8")

            self.assertEqual(engine_environment_path(staging, target, "win32"), target)
            self.assertFalse(target.exists())
            self.assertTrue(target.parent.is_dir())

    def test_windows_copy_is_validated_before_promotion_and_keeps_extracted_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "engines/runtime"
            source.mkdir()
            (source / "infer.py").write_text("ready", encoding="utf-8")

            place_windows_directory(source, target, lambda path: self.assertTrue((path / "infer.py").is_file()))

            self.assertTrue((source / "infer.py").is_file())
            self.assertEqual((target / "infer.py").read_text(encoding="utf-8"), "ready")
            self.assertEqual(list(target.parent.glob(".*.install-*")), [])

    def test_failed_validation_leaves_no_promoted_or_temporary_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "engines/runtime"
            source.mkdir()
            (source / "incomplete").write_text("x", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "incomplete"):
                place_windows_directory(source, target, lambda _path: (_ for _ in ()).throw(ValueError("incomplete")))

            self.assertFalse(target.exists())
            self.assertEqual(list(target.parent.glob(".*.install-*")), [])

    def test_sharing_violation_retries_with_a_fixed_limit(self):
        attempts = 0

        def eventually_succeeds():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise PermissionError("locked")

        with patch("server.modules.tts_install_placement.time.sleep") as sleep:
            retry_windows_file_operation(eventually_succeeds, attempts=3, delay=0.01)
        self.assertEqual(attempts, 3)
        self.assertEqual(sleep.call_count, 2)

        with patch("server.modules.tts_install_placement.time.sleep"):
            with self.assertRaises(PermissionError):
                retry_windows_file_operation(lambda: (_ for _ in ()).throw(PermissionError("locked")), attempts=2)


if __name__ == "__main__":
    unittest.main()

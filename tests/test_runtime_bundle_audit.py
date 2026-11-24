import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "audit-runtime-bundle.py"
SPEC = importlib.util.spec_from_file_location("runtime_bundle_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RuntimeBundleAuditTests(unittest.TestCase):
    def test_external_runtime_pins_non_pypi_forks_to_commits(self) -> None:
        requirements = (Path(__file__).parents[1] / "tools" / "omlx-runtime-requirements.txt").read_text()
        self.assertIn(
            "dflash-mlx @ git+https://github.com/jundot/dflash-mlx.git@b7f625504a733216d9e06caa3f7847a048241d94",
            requirements,
        )
        self.assertNotIn("dflash-mlx==", requirements)

    def test_reports_large_duplicate_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"x" * MODULE.LARGE_FILE_BYTES
            (root / "one.bin").write_bytes(payload)
            (root / "two.bin").write_bytes(payload)
            result = MODULE.audit(root)
        self.assertEqual([["one.bin", "two.bin"]], result["duplicateLargeFiles"])

    def test_reports_forbidden_package_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "_internal" / "pyarrow" / "lib.dylib"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"arrow")
            result = MODULE.audit(root)
        self.assertEqual(["_internal/pyarrow/lib.dylib"], result["forbiddenFiles"])

    def test_calculates_baseline_reduction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runtime").write_bytes(b"x" * 70)
            result = MODULE.audit(root, baseline=100)
        self.assertEqual(30.0, result["reductionPercent"])

    def test_symlink_is_not_counted_as_duplicate_storage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / "libmlx.dylib"
            payload.write_bytes(b"x" * MODULE.LARGE_FILE_BYTES)
            link = root / "mlx" / "lib" / "libmlx.dylib"
            link.parent.mkdir(parents=True)
            link.symlink_to(Path("../../libmlx.dylib"))
            result = MODULE.audit(root)
        self.assertEqual([], result["duplicateLargeFiles"])
        self.assertEqual(["mlx/lib/libmlx.dylib"], result["symlinks"])
        self.assertEqual([], result["brokenSymlinks"])

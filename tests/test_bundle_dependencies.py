"""The packaged API must not need development-only libraries."""

import scena_test_isolation  # noqa: F401
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# numpy stays a development dependency for audio reference tests; the app mixes audio in scena_native.
# hf_xet is installed with huggingface_hub but serves only uploads; SCENA downloads with urllib.
_IMPORT_WITHOUT_NUMPY = """
import importlib, pkgutil, sys
sys.modules["numpy"] = None
sys.modules["hf_xet"] = None
import server.app
import server.modules
for module in pkgutil.iter_modules(server.modules.__path__):
    importlib.import_module(f"server.modules.{module.name}")
"""


class BundleDependencyTests(unittest.TestCase):
    def test_api_modules_import_without_numpy_or_hf_xet(self):
        result = subprocess.run([sys.executable, "-c", _IMPORT_WITHOUT_NUMPY], cwd=ROOT, capture_output=True, text=True,
                                timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()

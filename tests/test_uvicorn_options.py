"""Uvicorn protocol choices must not depend on what else is importable next to the API."""

import scena_test_isolation  # noqa: F401
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_LOAD = """
import sys
sys.path.insert(0, sys.argv[1])
import uvicorn
from server.uvicorn_options import UVICORN_PROTOCOLS
async def app(scope, receive, send):
    pass
uvicorn.Config(app, **UVICORN_PROTOCOLS).load()
"""


class UvicornOptionsTests(unittest.TestCase):
    def test_stale_websockets_and_uvloop_folders_do_not_break_startup(self):
        # An in-place Windows install once left websockets/speedups.pyd and similar leftovers behind.
        with tempfile.TemporaryDirectory() as directory:
            for name, leftover in (("websockets", "speedups.cp313-win_amd64.pyd"), ("uvloop", "loop.cp313-win_amd64.pyd")):
                (Path(directory) / name).mkdir()
                (Path(directory) / name / leftover).write_bytes(b"")
            result = subprocess.run([sys.executable, "-c", _LOAD, directory], cwd=ROOT, capture_output=True, text=True,
                                    timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()

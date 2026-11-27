"""Point the backend at a throwaway data root before any server module loads.

Importing ``server.app`` restores the last workspace and seeds default files
under ``SCENA_DATA_ROOT`` at import time, so a test must never resolve that
root to the developer's real ``scena-data``. Every test module that imports
the backend imports this module first; ``test_scena_test_isolation`` enforces
that. Child processes inherit the same throwaway root through the environment.
The constants module is loaded here so a test that later clears
``os.environ`` (for example ``patch.dict(..., clear=True)``) cannot make a
first backend import fall back to the real root.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

DATA_ROOT = tempfile.mkdtemp(prefix="scena-test-data-")
os.environ["SCENA_DATA_ROOT"] = DATA_ROOT
atexit.register(shutil.rmtree, DATA_ROOT, True)

from server.modules import constants  # noqa: E402

if constants.DATA_ROOT.resolve() != Path(DATA_ROOT).resolve():
    raise RuntimeError("server constants were loaded before the test data root was isolated")

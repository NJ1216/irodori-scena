from __future__ import annotations

from pathlib import Path
from server import subprocess_boundary as subprocess


def directory_size(path: Path) -> int:
    try:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    except OSError:
        return 0


def installed_omlx_version(path: Path) -> str | None:
    try:
        result = subprocess.run(
            [str(path / "bin/python"), "-c", "import importlib.metadata as m;print(m.version('omlx'))"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None

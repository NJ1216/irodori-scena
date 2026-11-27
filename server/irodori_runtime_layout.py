"""Build the checkpoint layout expected by the pinned Irodori-TTS runtime."""

from __future__ import annotations

import errno
import json
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import psutil

TEMP_PREFIX = "irodori-scena-runtime-"
ADJACENT_PREFIX = ".scena-runtime-"
OWNER_MARKER = "scena-owner.json"


@dataclass(frozen=True)
class RuntimeCheckpoint:
    path: Path
    temporary_root: Path | None = None

    def cleanup(self) -> None:
        if self.temporary_root is not None:
            shutil.rmtree(self.temporary_root, ignore_errors=True)


def install_termination_cleanup() -> None:
    """Turn SIGTERM into a normal exit so the worker's finally blocks remove its runtime dirs."""
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda _signal, _frame: sys.exit(143))


def _write_owner_marker(root: Path) -> None:
    process = psutil.Process()
    (root / OWNER_MARKER).write_text(
        json.dumps({"pid": process.pid, "createTime": process.create_time()}), encoding="utf-8"
    )


def _owner_is_alive(root: Path) -> bool | None:
    """True/False for a readable owner marker; None when the directory has no valid marker."""
    try:
        marker = json.loads((root / OWNER_MARKER).read_text(encoding="utf-8"))
        pid, created = int(marker["pid"]), float(marker["createTime"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        return abs(psutil.Process(pid).create_time() - created) < 1.0
    except psutil.NoSuchProcess:
        return False
    except psutil.Error:
        # AccessDenied or any other inspection failure: a live process we cannot
        # inspect must never lose its runtime folder.
        return True


def sweep_stale_runtime_dirs(checkpoint_parent: Path | None = None) -> list[Path]:
    """Remove runtime dirs left by workers that could not clean up (kill, crash, power loss).

    Only SCENA's own prefixes in the temp directory and beside the model are considered.
    A directory is kept while the worker named by its owner marker is alive. A directory
    without a marker (older SCENA) is removed only when it predates the current boot,
    because no worker can survive a reboot.
    """
    roots = [Path(tempfile.gettempdir())]
    if checkpoint_parent is not None:
        roots.append(checkpoint_parent)
    removed: list[Path] = []
    for location in roots:
        try:
            candidates = [
                entry for entry in location.iterdir()
                if entry.name.startswith((TEMP_PREFIX, ADJACENT_PREFIX))
            ]
        except OSError:
            continue
        for entry in candidates:
            try:
                if entry.is_symlink() or not entry.is_dir():
                    continue
                alive = _owner_is_alive(entry)
                if alive is None:
                    alive = entry.stat().st_mtime >= psutil.boot_time()
                if alive:
                    continue
                shutil.rmtree(entry, ignore_errors=True)
                removed.append(entry)
            except OSError:
                continue
    return removed


def prepare_runtime_checkpoint(checkpoint: Path, tokenizer: Path) -> RuntimeCheckpoint:
    """Place a nested variant beside its shared tokenizer without copying model bytes."""
    sweep_stale_runtime_dirs(checkpoint.parent)
    if tokenizer.resolve() == (checkpoint.parent / "tokenizer").resolve():
        return RuntimeCheckpoint(checkpoint)

    root = Path(tempfile.mkdtemp(prefix=TEMP_PREFIX))
    try:
        _write_owner_marker(root)
        if sys.platform == "win32":
            # Windows symlinks normally require Developer Mode or elevation.
            # Managed models and the process temp directory live on the same
            # user-data volume, where a hard link needs neither privilege.
            try:
                os.link(checkpoint, root / "model.safetensors")
            except OSError as error:
                if error.errno != errno.EXDEV:
                    raise
                shutil.rmtree(root)
                root = Path(tempfile.mkdtemp(prefix=ADJACENT_PREFIX, dir=checkpoint.parent))
                _write_owner_marker(root)
                os.link(checkpoint, root / "model.safetensors")
            shutil.copytree(tokenizer, root / "tokenizer")
        else:
            (root / "model.safetensors").symlink_to(checkpoint.resolve())
            (root / "tokenizer").symlink_to(tokenizer.resolve(), target_is_directory=True)
        return RuntimeCheckpoint(root / "model.safetensors", root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise

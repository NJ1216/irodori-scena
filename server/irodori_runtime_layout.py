"""Build the checkpoint layout expected by the pinned Irodori-TTS runtime."""

from __future__ import annotations

import errno
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeCheckpoint:
    path: Path
    temporary_root: Path | None = None

    def cleanup(self) -> None:
        if self.temporary_root is not None:
            shutil.rmtree(self.temporary_root, ignore_errors=True)


def prepare_runtime_checkpoint(checkpoint: Path, tokenizer: Path) -> RuntimeCheckpoint:
    """Place a nested variant beside its shared tokenizer without copying model bytes."""
    if tokenizer.resolve() == (checkpoint.parent / "tokenizer").resolve():
        return RuntimeCheckpoint(checkpoint)

    root = Path(tempfile.mkdtemp(prefix="irodori-scena-runtime-"))
    try:
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
                root = Path(tempfile.mkdtemp(prefix=".scena-runtime-", dir=checkpoint.parent))
                os.link(checkpoint, root / "model.safetensors")
            shutil.copytree(tokenizer, root / "tokenizer")
        else:
            (root / "model.safetensors").symlink_to(checkpoint.resolve())
            (root / "tokenizer").symlink_to(tokenizer.resolve(), target_is_directory=True)
        return RuntimeCheckpoint(root / "model.safetensors", root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise

"""Shared metadata helpers for reproducible inference baselines."""

from __future__ import annotations

import hashlib
import subprocess
import wave
from pathlib import Path


def git_revision(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def wav_details(path: Path) -> dict[str, float | int | str]:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        sample_rate = wav.getframerate()
        return {
            "channels": wav.getnchannels(),
            "sample_width_bytes": wav.getsampwidth(),
            "sample_rate": sample_rate,
            "frames": frames,
            "duration_seconds": round(frames / sample_rate, 6),
            "compression_type": wav.getcomptype(),
            "compression_name": wav.getcompname(),
        }

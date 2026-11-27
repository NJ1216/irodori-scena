from __future__ import annotations

import scena_test_isolation  # noqa: F401
import hashlib
import subprocess
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.baseline_utils import git_revision, sha256, wav_details


class BaselineUtilityTests(unittest.TestCase):
    def test_hash_and_wav_metadata_are_stable(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8_000)
                output.writeframes(b"\x00\x00" * 4_000)

            self.assertEqual(sha256(path), hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(
                wav_details(path),
                {
                    "channels": 1,
                    "sample_width_bytes": 2,
                    "sample_rate": 8_000,
                    "frames": 4_000,
                    "duration_seconds": 0.5,
                    "compression_type": "NONE",
                    "compression_name": "not compressed",
                },
            )

    def test_git_revision_uses_a_fixture_checkout_and_handles_source_archives(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(git_revision(root))
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run([
                "git", "-C", str(root), "-c", "user.name=Fixture",
                "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgSign=false",
                "-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "fixture",
            ], check=True)
            revision = git_revision(root)
            self.assertIsNotNone(revision)
            self.assertEqual(len(revision or ""), 40)

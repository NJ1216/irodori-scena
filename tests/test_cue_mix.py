import scena_test_isolation  # noqa: F401
import server.app  # noqa: F401  (registers the backend dependencies these modules read)
import math
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from server.modules.cue_mix import MIX_ALGORITHM_VERSION, TRUE_PEAK_LIMIT, audio_file_identity, mix_pcm_members


def write_tone(path: Path, *, amplitude: float, seconds: float, rate: int = 48_000) -> None:
    positions = np.arange(round(rate * seconds)) / rate
    samples = np.round(np.sin(2 * math.pi * 440 * positions) * amplitude * 32767).astype("<i2")
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples.tobytes())


class CueMixTests(unittest.TestCase):
    def test_audio_identity_changes_when_regeneration_overwrites_the_same_path(self):
        self.assertEqual(MIX_ALGORITHM_VERSION, "cue-mix-v3")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "take.wav"
            write_tone(path, amplitude=0.2, seconds=0.1)
            before = audio_file_identity(path)
            write_tone(path, amplitude=0.4, seconds=0.1)
            self.assertNotEqual(before, audio_file_identity(path))

    def test_mix_places_members_at_offsets_and_prevents_clipping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, output = root / "first.wav", root / "second.wav", root / "mix.wav"
            write_tone(first, amplitude=0.8, seconds=0.25)
            write_tone(second, amplitude=0.8, seconds=0.5)
            duration = mix_pcm_members([(first, 0), (second, 0.2)], output)
            self.assertLess(abs(duration - 0.7), 1 / 48_000)
            with wave.open(str(output), "rb") as reader:
                samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32) / 32768
            self.assertLessEqual(float(np.max(np.abs(samples))), TRUE_PEAK_LIMIT + 1 / 32768)
            self.assertTrue(np.any(samples[:round(0.1 * 48_000)]))

    def test_silent_mix_remains_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            silent, output = root / "silent.wav", root / "mix.wav"
            write_tone(silent, amplitude=0, seconds=0.1)
            mix_pcm_members([(silent, 0), (silent, 0.1)], output)
            with wave.open(str(output), "rb") as reader:
                self.assertFalse(any(reader.readframes(reader.getnframes())))

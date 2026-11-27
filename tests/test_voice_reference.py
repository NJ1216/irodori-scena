from __future__ import annotations

import scena_test_isolation  # noqa: F401
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException
from server.modules.voice_reference import concatenate_reference_wavs, validate_voice_design_clip, wav_duration


def write_wav(path: Path, *, seconds: float, rate: int = 10) -> None:
    with wave.open(str(path), "wb") as target:
        target.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        target.writeframes(b"\0\0" * int(seconds * rate))


class VoiceReferenceTests(unittest.TestCase):
    def test_concatenates_in_given_order_and_trims_to_120_seconds(self) -> None:
        with TemporaryDirectory() as directory:
            paths = [Path(directory) / f"{index}.wav" for index in range(6)]
            for path in paths:
                write_wav(path, seconds=15)
            audio = concatenate_reference_wavs(paths)
            target = Path(directory) / "joined.wav"
            target.write_bytes(audio)
            self.assertEqual(wav_duration(target), 93.5)

    def test_accepts_a_clip_up_to_the_30_second_generation_ceiling(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "ceiling.wav"
            write_wav(path, seconds=30)
            self.assertEqual(validate_voice_design_clip(path), 30.0)

    def test_rejects_a_clip_longer_than_30_seconds_with_a_coded_message(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "long.wav"
            write_wav(path, seconds=31)
            with self.assertRaises(HTTPException) as raised:
                validate_voice_design_clip(path)
            self.assertEqual(raised.exception.status_code, 422)
            self.assertEqual(raised.exception.detail["code"], "voice_design_clip_too_long")
            self.assertIn("30秒以内", raised.exception.detail["message"])

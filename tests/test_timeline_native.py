from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import scena_native
import server.app  # noqa: F401
from server.modules.timeline_export import export_timeline, write_timeline_wav
from server.modules.export_audio import join_wav_files


def read(path):
    with wave.open(str(path), "rb") as reader:
        return np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")


class TimelineNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)
        self.source = self.root / "source.wav"
        with wave.open(str(self.source), "wb") as writer:
            writer.setparams((1, 2, 1000, 0, "NONE", "not compressed"))
            writer.writeframes(np.round(np.sin(np.arange(3000) * 0.137) * 20000).astype("<i2").tobytes())

    def test_native_interval_cancel_does_not_publish(self):
        output = self.root / "cancel.wav"
        with self.assertRaises(InterruptedError):
            scena_native.render_timeline_wav([(self.source, 0, 3000)], 0, 1000, 1000, 1, output, lambda: True)
        self.assertFalse(output.exists())

    def test_export_and_subtitle_member_offsets_use_same_reversed_timeline(self):
        def line(key, **extra):
            return {
                "id": key,
                "text": key,
                "characterId": "cast",
                "selectedTakeId": "t",
                "takes": [{"id": "t", "audioUrl": "x"}],
                **extra,
            }

        a, b, c = (
            line("a", cueId="cue", startOffsetSeconds=0, gapSeconds=-4),
            line("b", cueId="cue", startOffsetSeconds=2),
            line("c"),
        )
        scene = {"lines": [a, b, c]}
        project = {"id": "p", "settings": {"lineGap": 0}, "scenes": [scene]}
        with (
            patch("server.modules.export_service.take_audio_path", return_value=self.source),
            patch("server.modules.constants.MEDIA_ROOT", self.root),
            patch("server.modules.cue_mix.audio_file_identity", return_value="audio-hash"),
        ):
            plan, entries = export_timeline(
                project, [SimpleNamespace(line=item, text=item["text"]) for item in [a, b, c]]
            )
            self.assertEqual(entries, [("a", 0, 3), ("c", 1, 4), ("b", 2, 5)])
            output = self.root / "joined.wav"
            write_timeline_wav(plan, output)
            reference = self.root / "full.wav"
            scena_native.render_timeline_wav(
                [(self.source, 0, 3000), (self.source, 2000, 3000), (self.source, 1000, 3000)],
                0,
                5000,
                1000,
                1,
                reference,
            )
            np.testing.assert_array_equal(read(output), read(reference))

    def test_three_way_legacy_join_uses_new_mixer_without_adjacent_cache(self):
        output = self.root / "joined.wav"
        with (
            patch("server.modules.constants.MEDIA_ROOT", self.root),
            patch("server.modules.cue_mix.audio_file_identity", return_value="hash"),
        ):
            join_wav_files([(self.source, -2.5)] * 3, output)
        self.assertEqual(len(read(output)), 4000)
        self.assertLessEqual(np.max(np.abs(read(output).astype(np.int32))), 29205)

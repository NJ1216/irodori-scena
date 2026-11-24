"""Protect timing and quiet boundaries in the offline smoothing experiment."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from lipsync_temporal import bridge_uncertain_frames, suppress_short_vowels
from evaluate_japanese_lipsync import acoustic


class TemporalTests(unittest.TestCase):
    def test_bridge_requires_matching_vowels_and_bounded_gap(self):
        self.assertEqual(bridge_uncertain_frames(["a", None, None, "a"]), ["a"] * 4)
        for frames in (["a", None, "e"], ["N", None, "N"],
                       ["a", *([None] * 7), "a"], [None, "a"]):
            self.assertEqual(bridge_uncertain_frames(frames), frames)

    def test_remove_excursion_without_moving_silence_or_closure(self):
        rows = [(0, 1_000_000, "a"), (1_000_000, 1_200_000, "e"),
                (1_200_000, 2_000_000, "a"), (2_000_000, 2_200_000, "N"),
                (2_200_000, 2_400_000, "i"), (2_400_000, 3_000_000, "pau")]
        self.assertEqual(suppress_short_vowels(rows), [(0, 2_000_000, "a"), *rows[3:]])

    def test_sustained_vowel_switch_retained(self):
        rows = [(0, 800_000, "a"), (800_000, 1_400_000, "e"),
                (1_400_000, 2_200_000, "i")]
        self.assertEqual(suppress_short_vowels(rows), rows)

    def test_acoustic_gap_does_not_replace_baseline_closed_lips(self):
        rows = [(0, 200_000, "a"), (200_000, 400_000, "N"),
                (400_000, 800_000, "a")]
        with patch("evaluate_japanese_lipsync.acoustic_frames",
                   return_value=(["a", None, None, "a"], 0.02)):
            result = acoustic(rows, np.zeros(800), 10_000, stabilize=True)
        self.assertEqual(result, rows)

    def test_uncertain_speech_keeps_baseline_known_vowel_and_quiet_boundaries(self):
        rows = [(0, 1_000_000, "i"), (1_000_000, 1_800_000, "i"),
                (1_800_000, 2_200_000, "N"), (2_200_000, 2_600_000, "pau")]
        frames = [None] * 5 + ["a"] * 4 + [None] * 4
        with patch("evaluate_japanese_lipsync.acoustic_frames", return_value=(frames, 0.02)):
            result = acoustic(rows, np.zeros(2600), 10_000, stabilize=True)
        self.assertEqual(result, [(0, 1_000_000, "i"), (1_000_000, 1_800_000, "a"), *rows[2:]])


class SupportedShortVowelTests(unittest.TestCase):
    def test_short_acoustically_supported_vowel_is_preserved(self):
        from lipsync_temporal import suppress_short_vowels
        rows = [(0, 1_000_000, "i"), (1_000_000, 1_300_000, "a"), (1_300_000, 3_000_000, "i")]
        self.assertEqual(suppress_short_vowels(rows, protected=[(1_050_000, 1_200_000, "a")]), rows)


if __name__ == "__main__":
    unittest.main()

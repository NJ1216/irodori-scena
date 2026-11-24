"""Safety fixtures for the offline CTC correction candidate."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from lipsync_ctc_probe import conv_timing, correct_uncertain, recognize, vowel_proposals


class CTCCorrectionTests(unittest.TestCase):
    def test_convolution_frame_centers(self):
        config = {"conv_kernel": [10, 3, 3, 3, 3, 2, 2], "conv_stride": [5, 2, 2, 2, 2, 2, 2]}
        self.assertEqual(conv_timing(config), (0.02, 0.0125))

    def test_low_confidence_skipped_and_trailing_hold_bounded(self):
        events = [{"time": 0.1, "phone": "a", "confidence": 0.7},
                  {"time": 0.5, "phone": "o", "confidence": 0.99}]
        self.assertEqual(vowel_proposals(events, 2), [(4_900_000, 8_000_000, "o")])

    def test_only_uncertain_speech_changes(self):
        rows = [(0, 1_000_000, "a"), (1_000_000, 2_000_000, "i"),
                (2_000_000, 2_400_000, "N"), (2_400_000, 3_000_000, "pau")]
        observations = ["a"] * 5 + [None] * 10
        result = correct_uncertain(rows, [(0, 3_000_000, "o")], observations, 0.02)
        self.assertEqual(result, [rows[0], (1_000_000, 2_000_000, "o"), *rows[2:]])
        self.assertEqual(correct_uncertain(rows, [], observations, 0.02), rows)

    def test_blank_is_not_silence_and_processor_normalization_is_obeyed(self):
        class Session:
            def run(self, _, feed):
                np.testing.assert_array_equal(feed["input_values"], [[0.25] * 400])
                return [np.array([[[20, 0], [0, 20], [20, 0]]], dtype=float)]
        events = recognize(Session(), np.full(400, 0.25), 16000, {"PAD": 0, "o": 1},
                           {"conv_kernel": [1], "conv_stride": [320]}, {"do_normalize": False})
        self.assertEqual([event["phone"] for event in events], ["o"])


class CTCFrameEvidenceTests(unittest.TestCase):
    def test_optional_candidates_include_non_greedy_phone_probability(self):
        class Session:
            def run(self, *_):
                return [np.array([[[3, 2, 1], [0, 3, 2]]], dtype=float)]
        events, frames = recognize(Session(), np.ones(400), 16000, {"PAD": 0, "i": 1, "a": 2},
                                  {"conv_kernel": [1], "conv_stride": [320]},
                                  {"do_normalize": False}, with_frames=True)
        self.assertEqual([e["phone"] for e in events], ["i"])
        self.assertEqual(len(frames), 2)
        self.assertGreater(frames[1]["candidates"]["a"], 0)
        self.assertAlmostEqual(sum(frames[1]["candidates"].values()), 1)

    def test_incremental_correction_preserves_other_short_baseline_vowels(self):
        rows = [(0, 1_000_000, "i"), (1_000_000, 1_200_000, "e"), (1_200_000, 3_000_000, "i")]
        result = correct_uncertain(rows, [(2_000_000, 3_000_000, "a")], [None] * 15, 0.02,
                                   protect_supported=True)
        self.assertIn(rows[1], result)
        self.assertEqual(result[-1][2], "a")

    def test_tiny_unsupported_excursion_within_supported_vowel_is_smoothed(self):
        rows = [(0, 2_000_000, "i"), (2_000_000, 3_000_000, "e")]
        observations = [None, None, None, None, "i", None, None, None, None, None, "e", "e", "e", "e", "e"]
        result = correct_uncertain(rows, [(625_000, 1_825_000, "a")], observations, 0.02,
                                   protect_supported=True)
        self.assertEqual(result, [(0, 625_000, "i"), (625_000, 1_825_000, "a"), (1_825_000, 3_000_000, "e")])


if __name__ == "__main__":
    unittest.main()

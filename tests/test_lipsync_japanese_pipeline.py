"""Inference reuse is exact, rate-sensitive and confined to one WAV request."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_japanese_pipeline import memoized_recognizer, refine_japanese
from evaluate_japanese_lipsync import acoustic


class PipelineReuseTests(unittest.TestCase):
    def test_stage_snapshots_are_immutable_and_do_not_change_results(self):
        rows, audio = [(0, 10_000_000, 'pau')], np.zeros(16000)
        baseline = refine_japanese(rows, audio, 16000, lambda *_: ([], []), confirm_vowels=True)
        snapshots = {}
        traced = refine_japanese(rows, audio, 16000, lambda *_: ([], []), confirm_vowels=True,
                                  snapshot=lambda name, value: snapshots.update({name: value}))
        self.assertEqual(traced, baseline)
        self.assertEqual(snapshots['original'], ((0, 10_000_000, 'pau'),))
        self.assertEqual(snapshots['confirmedVowels'], snapshots['original'])
        rows[0] = (0, 10_000_000, 'a')
        self.assertEqual(snapshots['original'][0][2], 'pau')

    def test_precomputed_acoustic_frames_preserve_output_and_input(self):
        from unittest.mock import patch

        frames = (['a'] * 8 + [None] * 2 + ['a'] * 8 + ['N'] * 2, .01)
        original = list(frames[0])
        rows = [(0, 2_000_000, 'i')]
        audio = np.zeros(3200)
        with patch('evaluate_japanese_lipsync.acoustic_frames', return_value=frames) as extract:
            baseline = acoustic(rows, audio, 16000, stabilize=True)
            reused = acoustic(rows, audio, 16000, stabilize=True, frame_observations=frames)
        self.assertEqual(baseline, reused)
        self.assertEqual(frames[0], original)
        extract.assert_called_once()

    def test_identical_crop_reuses_result_but_changed_samples_or_rate_do_not(self):
        infer = Mock(return_value=([], []))
        recognize = memoized_recognizer(infer)
        audio = np.array([.1, .2, .3])
        recognize(audio, 16000)
        recognize(audio.copy(), 16000)
        self.assertEqual(infer.call_count, 1)
        recognize(audio, 48000)
        recognize(audio + 1e-12, 16000)
        self.assertEqual(infer.call_count, 3)

    def test_new_request_does_not_reuse_previous_request_audio(self):
        infer = Mock(return_value=([], []))
        audio = np.array([.1, .2])
        memoized_recognizer(infer)(audio, 16000)
        memoized_recognizer(infer)(audio, 16000)
        self.assertEqual(infer.call_count, 2)

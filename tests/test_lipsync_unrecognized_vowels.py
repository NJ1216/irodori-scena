"""Unrecognized single-vowel fallback must not erase supported transitions."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_unrecognized_vowels import preserve_unrecognized_vowels


class UnrecognizedVowelsTests(unittest.TestCase):
    def setUp(self):
        self.original = [(0, 3_100_000, 'u'), (3_100_000, 6_500_000, 'N'),
                         (6_500_000, 20_000_000, 'pau')]
        self.candidate = [(0, 1_600_000, 'u'), (1_600_000, 2_400_000, 'o'),
                          (2_400_000, 3_100_000, 'u'), (3_100_000, 4_600_000, 'N'),
                          (4_600_000, 5_600_000, 'a'), (5_600_000, 6_200_000, 'N'),
                          (6_200_000, 20_000_000, 'pau')]
        self.audio = np.zeros(2000)

    def run_fallback(self, events=(), recognizer=lambda *_: ([], []), original=None):
        return preserve_unrecognized_vowels(original or self.original, self.candidate, events,
                                             self.audio, 1000, recognizer)

    def test_weak_crop_and_formants_cannot_invent_vowel_changes(self):
        result, audit = self.run_fallback(recognizer=lambda *_: (
            [{'time': .13, 'phone': 'a', 'confidence': .908}], []))
        self.assertEqual(result, [(0, 3_100_000, 'u'), (3_100_000, 6_200_000, 'N'),
                                  (6_200_000, 20_000_000, 'pau')])
        self.assertEqual(len(audit), 1)

    def test_supported_transition_in_full_or_either_crop_is_retained(self):
        event = {'time': .13, 'phone': 'a', 'confidence': .99}
        self.assertEqual(self.run_fallback(events=[event])[0], self.candidate)
        for position in (0, 1):
            calls = []
            def infer(*_):
                i = len(calls)
                calls.append(i)
                return ([{**event, 'time': .53 if i else .13}] if i == position else [], [])
            self.assertEqual(self.run_fallback(recognizer=infer)[0], self.candidate)

    def test_multiple_original_vowels_are_not_flattened(self):
        original = [(0, 1_600_000, 'u'), (1_600_000, 3_100_000, 'o'), *self.original[1:]]
        self.assertEqual(self.run_fallback(original=original), (self.candidate, []))

    def test_failed_retry_keeps_current_result(self):
        def fail(*_):
            raise RuntimeError('failed')
        self.assertEqual(self.run_fallback(recognizer=fail), (self.candidate, []))


if __name__ == '__main__':
    unittest.main()

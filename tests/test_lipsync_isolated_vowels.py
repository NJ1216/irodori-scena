"""Independent vowels require two acoustic confirmations and retain pause/closure evidence."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_isolated_vowels import recover_isolated_vowels


def frame(time, phone, probability):
    return {'time': time, 'candidates': {phone: probability, 'PAD': 1 - probability}}


class IsolatedVowelTests(unittest.TestCase):
    def setUp(self):
        self.rows = [(0, 10_000_000, 'pau'), (10_000_000, 11_200_000, 'i'),
                     (11_200_000, 20_000_000, 'pau')]
        self.audio = np.full(2000, .1)
        self.full = [frame(1.05, 'a', .93)]

    def recognize(self, segment, rate):
        prefix = .4 if np.all(segment[:400] == 0) else 0
        start = .6 if prefix else .8
        return [], [frame(1.05 - start + prefix, 'a', .99)]

    def test_independent_vowel_is_confirmed_without_consonant_and_pauses_retained(self):
        after, audit = recover_isolated_vowels(self.rows, self.full, self.audio, 1000, self.recognize)
        self.assertEqual(after, [self.rows[0], (10_000_000, 11_200_000, 'a'), self.rows[2]])
        self.assertEqual(len(audit['attempts']), 2)

    def test_disagreement_or_failure_keeps_existing_vowel(self):
        for failure in (False, True):
            count = 0

            def recognize(segment, rate):
                nonlocal count
                count += 1
                if count == 2:
                    if failure:
                        raise RuntimeError('failed')
                    return [], [frame(.85, 'e', .99)]
                return self.recognize(segment, rate)

            after, _ = recover_isolated_vowels(self.rows, self.full, self.audio, 1000, recognize)
            self.assertEqual(after, self.rows)

    def test_supported_full_vowel_and_closure_are_protected(self):
        full = [*self.full, frame(1.10, 'cl', .99)]
        after, _ = recover_isolated_vowels(self.rows, full, self.audio, 1000, self.recognize)
        self.assertTrue(any(a <= 10_800_000 < b and s == 'i' for a, b, s in after))
        after, _ = recover_isolated_vowels(self.rows, [frame(1.05, 'a', .99)],
                                           self.audio, 1000, self.recognize)
        self.assertTrue(any(a <= 10_500_000 < b and s == 'i' for a, b, s in after))

    def test_long_or_nonisolated_vowel_does_not_trigger(self):
        for rows in ([(0, 10_000_000, 'N'), *self.rows[1:]],
                     [(0, 10_000_000, 'pau'), (10_000_000, 13_000_000, 'i'),
                      (13_000_000, 20_000_000, 'pau')]):
            after, audit = recover_isolated_vowels(rows, self.full, self.audio, 1000, self.recognize)
            self.assertEqual(after, rows)
            self.assertEqual(audit['attempts'], [])

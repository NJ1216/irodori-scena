"""Two-context confirmation never substitutes script guesses for acoustic evidence."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_confirmed_vowels import confirm_missed_vowels, target_window


def frames(start=.4, shape='e', confidence=.93):
    return [{'time': start, 'candidates': {'t': .93, 'PAD': .01}},
            {'time': start + .02, 'candidates': {shape: confidence, 'PAD': .01}},
            {'time': start + .08, 'candidates': {'r': .93, 'PAD': .01}}]


class ConfirmedVowelsTests(unittest.TestCase):
    def run_case(self, *, second='e', failure=False, silent=False, rows=None):
        audio = np.zeros(1000) if silent else np.full(1000, .1)
        # Target nucleus=.42. Group crop starts .12 (first) and 0 (second),
        # and the second crop has a .4 second synthetic prefix.
        calls = []
        def recognize(samples, rate):
            calls.append(len(samples))
            if failure and len(calls) == 2:
                raise RuntimeError('fixture failure')
            offset, shape = (.12, 'e') if len(calls) == 1 else (-.4, second)
            return [], frames(.4 - offset, shape, .99)
        original = rows or [(0, 10_000_000, 'i')]
        actual, audit = confirm_missed_vowels(original, frames(), audio, 1000, recognize)
        return original, actual, audit, calls

    def test_two_agreeing_contexts_correct_vowel_without_reading(self):
        _, actual, audit, calls = self.run_case()
        self.assertEqual(len(calls), 2)
        self.assertIn((3_900_000, 4_700_000, 'e'), actual)
        self.assertEqual(len(audit['windows']), 1)
        self.assertEqual(audit['textInfluence'], 'none')

    def test_disagreement_or_failure_preserves_input(self):
        for options in ({'second': 'a'}, {'failure': True}):
            original, actual, audit, _ = self.run_case(**options)
            self.assertEqual(actual, original)
            self.assertEqual(audit['windows'], [])

    def test_silence_does_not_open_mouth(self):
        original, actual, _, _ = self.run_case(silent=True)
        self.assertEqual(actual, original)

    def test_closure_and_pause_remain_untouched(self):
        rows = [(0, 4_000_000, 'pau'), (4_000_000, 4_300_000, 'i'),
                (4_300_000, 4_500_000, 'N'), (4_500_000, 10_000_000, 'i')]
        _, actual, _, _ = self.run_case(rows=rows)
        self.assertIn(rows[0], actual)
        self.assertIn(rows[2], actual)

    def test_already_matching_vowel_does_not_retry(self):
        original, actual, audit, calls = self.run_case(rows=[(0, 10_000_000, 'e')])
        self.assertEqual(actual, original)
        self.assertEqual(calls, [])
        self.assertEqual(audit['targetCount'], 0)

    def test_adopted_competing_nucleus_blocks_whole_overwrite(self):
        original, _, _, _ = self.run_case()
        calls = []
        def recognize(samples, rate):
            calls.append(len(samples))
            offset = .12 if len(calls) == 1 else -.4
            return [], frames(.4 - offset, 'e', .99)
        actual, audit = confirm_missed_vowels(original, frames(), np.full(1000, .1), 1000,
                                             recognize, protected=[(4_100_000, 4_300_000, 'i')])
        self.assertEqual(actual, original)
        self.assertEqual(audit['decisions'][0]['reason'], 'adopted_nucleus_conflict')

    def test_blank_hold_ends_at_earliest_context_phone_and_is_bounded(self):
        events = [{'time': .4, 'phone': 'e', 'coreEndTime': .4}, {'time': .8, 'phone': 'r'}]
        self.assertEqual(target_window(0, events, 1)[1], 6_500_000)
        self.assertEqual(target_window(0, events, 1, [{'nextTime': .54}, {'nextTime': .6}])[1], 5_300_000)


if __name__ == '__main__':
    unittest.main()

"""Local retries cannot manufacture prefix speech or overwrite accepted evidence."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_context_recovery import (absolute_frames, apply_windows, context_gaps,
                                     recover_context, recovered_windows)


def frames(*items):
    return [{'time': t, 'candidates': {phone: p, 'PAD': 1 - p}} for t, phone, p in items]


class ContextRecoveryTests(unittest.TestCase):
    def test_interior_second_retry_uses_neutral_context_and_richer_support(self):
        audio = np.full(3000, 0.1)
        rows = [(0, 10_000_000, 'pau'), (10_000_000, 20_000_000, 'i'),
                (20_000_000, 30_000_000, 'pau')]
        calls = []

        def recognize(segment, rate):
            calls.append(segment)
            if len(calls) == 1:
                return [], frames((0.3, 'k', .99), (0.32, 'a', .99))
            self.assertTrue(np.all(segment[:400] == 0))
            return [], frames((.39, 'a', .99), (.8, 'k', .99), (.82, 'a', .99),
                              (1.2, 't', .99), (1.22, 'e', .99))

        after, audit = recover_context(rows, [], audio, 1000, recognize)
        self.assertEqual(len(calls), 2)
        self.assertEqual([r for r in after if r[2] == 'pau'], [rows[0], rows[-1]])
        self.assertFalse(audit['attempts'][0]['selected'])
        self.assertTrue(audit['attempts'][1]['selected'])
        self.assertTrue(any(r[2] == 'e' for r in after))
        self.assertTrue(all(f['time'] >= .6 for f in audit['attempts'][1]['frames']))

    def test_synthetic_and_out_of_crop_frames_are_rejected(self):
        result = absolute_frames(frames((.39, 'a', .99), (.4, 'i', .99), (1.41, 'e', .99)), 1, 2, .4)
        self.assertEqual([f['time'] for f in result], [1])
        with self.assertRaises(ValueError):
            absolute_frames(frames((.5, 'a', .99), (.4, 'i', .99)), 1, 2, .4)

    def test_failures_and_unsupported_vowels_retain_baseline(self):
        rows = [(0, 10_000_000, 'i')]
        for recognize in (lambda *_: ([], frames((.2, 'k', .99), (.22, 'a', .5))),
                          lambda *_: (_ for _ in ()).throw(RuntimeError('inference')),
                          lambda *_: ([], [{'time': .2, 'candidates': {'a': float('nan')}}])):
            after, audit = recover_context(rows, [], np.full(1000, .1), 1000, recognize)
            self.assertEqual(after, rows)
            self.assertEqual(len(audit['attempts']), 2)

    def test_n_pause_and_supported_cores_are_preserved(self):
        rows = [(0, 2_000_000, 'i'), (2_000_000, 4_000_000, 'N'),
                (4_000_000, 6_000_000, 'pau'), (6_000_000, 10_000_000, 'i')]
        after = apply_windows(rows, [(0, 10_000_000, 'a')], [(6_000_000, 8_000_000, 'i')],
                              np.full(1000, .1), 1000)
        self.assertIn(rows[1], after)
        self.assertIn(rows[2], after)
        self.assertIn((6_000_000, 8_000_000, 'i'), after)

    def test_gap_grouping_never_crosses_pause_or_quiet_audio(self):
        rows = [(0, 4_000_000, 'i'), (4_000_000, 5_000_000, 'pau'), (5_000_000, 9_000_000, 'a')]
        self.assertEqual(len(context_gaps([], rows, np.full(900, .1), 1000)), 2)
        self.assertEqual(context_gaps([], rows, np.zeros(900), 1000), [])
        self.assertEqual(context_gaps([], [(0, 9_000_000, 'N')], np.full(900, .1), 1000), [])

    def test_repeated_and_hiatus_vowels_survive_without_crossing_pause(self):
        local = frames((.1, 'k', .99), (.12, 'a', .99), (.14, 'a', .99),
                       (.3, 'e', .99), (.32, 'e', .99))
        rows = [(0, 4_000_000, 'i'), (4_000_000, 5_000_000, 'pau'),
                (5_000_000, 10_000_000, 'i')]
        windows, _, _ = recovered_windows(local, rows, 1, 0, 1)
        self.assertEqual([w[2] for w in windows], ['a', 'e'])
        self.assertTrue(all(w[1] <= 4_000_000 for w in windows))

    def test_short_near_strong_vowel_only_triggers_confirmation_retry(self):
        rows = [(0, 10_000_000, 'i')]
        local = frames((.4, 'k', .99), (.42, 'e', .946), (.44, 'e', .55))
        gaps = context_gaps(local, rows, np.zeros(1000), 1000)
        self.assertEqual(len(gaps), 1)
        after, audit = recover_context(rows, local, np.zeros(1000), 1000, lambda *_: ([], []))
        self.assertEqual(after, rows)
        self.assertEqual(len(audit['attempts']), 2)
        self.assertEqual(context_gaps(frames((.4, 'k', .8), (.42, 'e', .946), (.44, 'e', .55)),
                                      rows, np.zeros(1000), 1000), [])


if __name__ == '__main__':
    unittest.main()

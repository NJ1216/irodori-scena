"""Common nucleus detection retains legacy behavior and isolates worker contexts."""
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_articulation import core_events, refine_articulation
from lipsync_vowel_evidence import adopted_nuclei, join_unsupported_fragments, onset_supported, vowel_evidence_policy


def evidence(probabilities, competitors=None):
    competitors = competitors or [min(.15, 1 - p) for p in probabilities]
    return [{'time': .1 + i * .02, 'candidates': {'e': p, 'PAD': c}}
            for i, (p, c) in enumerate(zip(probabilities, competitors))]


class NucleusEvidenceTests(unittest.TestCase):
    def test_vowel_calibration_does_not_change_closed_mouth_intervals(self):
        import numpy as np
        frames = [{'time': .0925, 'candidates': {'t': .88, 'PAD': .12}},
                  {'time': .1125, 'candidates': {'t': .999, 'PAD': .001}},
                  {'time': .1325, 'candidates': {'e': .999, 'PAD': .001}},
                  {'time': .1525, 'candidates': {'e': .999, 'PAD': .001}}]
        rows = [(0, 1_200_000, 'i'), (1_200_000, 1_400_000, 'N'), (1_400_000, 3_000_000, 'a')]
        baseline, _ = refine_articulation(rows, frames, np.full(300, .1), 1000)
        with vowel_evidence_policy(True):
            adjusted, _ = refine_articulation(rows, frames, np.full(300, .1), 1000)
        self.assertEqual([r for r in adjusted if r[2] == 'N'], [r for r in baseline if r[2] == 'N'])
        self.assertNotEqual(adjusted, baseline)

    def test_onset_uses_strong_core_only_in_common_profile(self):
        onset = {'confidence': .8, 'peak': .999, 'coreSupported': True}
        self.assertFalse(onset_supported(onset))
        with vowel_evidence_policy(True):
            self.assertTrue(onset_supported(onset))
            self.assertFalse(onset_supported({**onset, 'coreSupported': False}))

    def test_fragment_join_preserves_supported_short_vowels_and_closed_mouth(self):
        rows = [(0, 1_000_000, 'e'), (1_000_000, 1_075_000, 'i'), (1_075_000, 2_000_000, 'e')]
        self.assertEqual(join_unsupported_fragments(rows, [], [])[0], [(0, 2_000_000, 'e')])
        self.assertEqual(join_unsupported_fragments(rows, [], [(1_000_000, 1_075_000, 'i')])[0], rows)
        for label in ('N', 'pau'):
            closed = [rows[0], (1_000_000, 1_075_000, label), rows[2]]
            self.assertEqual(join_unsupported_fragments(closed, [], [])[0], closed)

    def test_weak_tails_do_not_erase_adjacent_clear_core(self):
        frames = evidence([.51, .7, .99, .51])
        self.assertFalse(core_events(frames)[0]['coreSupported'])
        with vowel_evidence_policy(True):
            self.assertTrue(core_events(frames)[0]['coreSupported'])
        self.assertFalse(core_events(frames)[0]['coreSupported'])

    def test_competing_frame_or_disconnected_peak_is_insufficient(self):
        for frames in (evidence([.51, .99], [.49, .01]), evidence([.7, .94]),
                       evidence([.99, .51, .99], [.01, .49, .01])):
            with vowel_evidence_policy(True):
                # Legacy strong nuclei remain accepted; no new support is added here.
                self.assertEqual(core_events(frames)[0]['coreSupported'], self.legacy(frames))
        frames = evidence([.7, .99, .51, .51], [.15, .01, .49, .49])
        frames[1]['time'] += .0011
        with vowel_evidence_policy(True):
            self.assertFalse(core_events(frames)[0]['coreSupported'])

    def legacy(self, frames):
        with vowel_evidence_policy(False):
            return core_events(frames)[0]['coreSupported']

    def test_parallel_workers_and_nested_scopes_do_not_leak_policy(self):
        frames = evidence([.51, .7, .99, .51])
        def run(enabled):
            with vowel_evidence_policy(enabled):
                with vowel_evidence_policy(False):
                    self.assertFalse(core_events(frames)[0]['coreSupported'])
                return core_events(frames)[0]['coreSupported']
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(run, [True, False] * 8)), [True, False] * 8)

    def test_only_adopted_nucleus_is_protected_not_blank_hold(self):
        rows = [(0, 10_000_000, 'e')]
        audit = {'attempts': [{'selected': True, 'gap': [.1, .3], 'frames': evidence([.99])},
                              {'selected': False, 'gap': [.1, .3], 'frames': evidence([.99])}]}
        self.assertEqual(adopted_nuclei(rows, audit), [(800_000, 1_200_000, 'e')])
        self.assertEqual(adopted_nuclei([(0, 10_000_000, 'i')], audit), [])
        self.assertEqual(adopted_nuclei(rows, {'attempts': audit['attempts'][:1]}), [])


if __name__ == '__main__':
    unittest.main()

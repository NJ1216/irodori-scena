"""Protect bilabial animation while recovering short acoustically supported vowels."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_articulation import align_labial_edges, closure_replacement, core_events, refine_articulation, safe_refine_articulation


def frames(sequence):
    return [{'time': time, 'candidates': {phone: probability, 'PAD': 1 - probability}}
            for time, phone, probability in sequence]


class ArticulationTests(unittest.TestCase):
    def test_low_average_with_consecutive_strong_core_recovers_short_vowel(self):
        evidence = frames([(0.0925, 'j', 0.999), (0.1125, 'i', 0.999), (0.1325, 'i', 0.72),
                           (0.1525, 'PAD', 1), (0.2125, 'm', 0.999), (0.2325, 'e', 0.999)])
        rows = [(0, 2_000_000, 'a'), (2_000_000, 2_300_000, 'N'), (2_300_000, 4_000_000, 'e')]
        result, audit = refine_articulation(rows, evidence, np.full(400, 0.1), 1000)
        self.assertIn((825_000, 1_725_000, 'i'), result)
        self.assertIn((1_725_000, 2_225_000, 'N'), result)
        self.assertTrue(any(e['reason'] == 'consecutive_core_frames' for e in audit['vowelEvidence']))

    def test_terminal_e_recovery_keeps_final_closed_mouth_and_pause(self):
        evidence = frames([(0.0925, 't', 0.99), (0.1125, 'e', 0.98), (0.1325, 'e', 0.67)])
        rows = [(0, 3_000_000, 'i'), (3_000_000, 3_700_000, 'N'), (3_700_000, 4_000_000, 'pau')]
        audio = np.concatenate((np.full(300, 0.1), np.zeros(100)))
        result, _ = refine_articulation(rows, evidence, audio, 1000)
        self.assertEqual(result[-2:], rows[-2:])
        self.assertTrue(any(label == 'e' for _, _, label in result))

    def test_m_b_p_closures_are_preserved_before_a_vowel(self):
        for phone in ('m', 'b', 'p', 'N', 'cl'):
            evidence = frames([(0.1925, phone, 0.999), (0.2125, 'a', 0.999),
                               (0.3125, 't', 0.999), (0.3325, 'e', 0.999)])
            rows = [(0, 1_525_000, 'i'), (1_525_000, 2_025_000, 'N'), (2_025_000, 4_000_000, 'a')]
            result, _ = refine_articulation(rows, evidence, np.full(400, 0.1), 1000)
            self.assertIn(rows[1], result, phone)

    def test_closure_trim_bounded_and_guarded_part_kept(self):
        row = (1_000_000, 1_800_000, 'N')
        result, audit = closure_replacement(row, [(0, 1_350_000, 'i')],
                                            [(1_350_000, 1_800_000, 'm')], np.full(300, 0.1), 1000)
        self.assertEqual(result, [(1_000_000, 1_350_000, 'i'), (1_350_000, 1_800_000, 'N')])
        self.assertEqual(audit[0]['reason'], 'bounded_closure_edge')

    def test_no_wholesale_removal_of_long_closure_or_unvoiced_closure(self):
        for row, audio in (((0, 1_000_000, 'N'), np.full(300, 0.1)),
                           ((0, 300_000, 'N'), np.zeros(300))):
            self.assertEqual(closure_replacement(row, [(0, 2_000_000, 'a')], [], audio, 1000)[0], [row])

    def test_short_nonlabial_closure_can_be_reviewed_separately(self):
        row = (1_000_000, 1_200_000, 'N')
        result, audit = closure_replacement(row, [(950_000, 1_300_000, 'a')], [], np.full(300, 0.1), 1000)
        self.assertEqual(result, [(1_000_000, 1_200_000, 'a')])
        self.assertEqual(audit[0]['reason'], 'short_nonlabial_closure')

    def test_blank_and_low_core_confidence_cannot_create_a_vowel(self):
        evidence = frames([(0.0925, 't', 0.999), (0.1125, 'e', 0.84), (0.1325, 'e', 0.66)])
        self.assertFalse(core_events(evidence)[1]['coreSupported'])
        rows = [(0, 4_000_000, 'i')]
        self.assertEqual(refine_articulation(rows, evidence, np.full(400, 0.1), 1000)[0], rows)
        self.assertEqual(refine_articulation(rows, [], np.full(400, 0.1), 1000)[0], rows)

    def test_vowel_hold_never_crosses_pause_into_next_phrase(self):
        evidence = frames([(0.0925, 't', 0.999), (0.1125, 'e', 0.999)])
        rows = [(0, 1_800_000, 'i'), (1_800_000, 2_400_000, 'pau'), (2_400_000, 4_000_000, 'a')]
        result, _ = refine_articulation(rows, evidence, np.full(400, 0.1), 1000)
        self.assertIn(rows[1], result)
        self.assertEqual(result[-1], rows[-1])

    def test_stop_plus_labial_overlap_preserves_entire_supported_closure(self):
        rows = [(17_000_000, 18_200_000, 'a'), (18_200_000, 19_000_000, 'N'),
                (19_000_000, 22_000_000, 'a')]
        events = [{'time': 1.8325, 'phone': 'cl', 'confidence': 0.99},
                  {'time': 1.8925, 'phone': 'p', 'confidence': 0.99},
                  {'time': 1.9125, 'phone': 'a', 'confidence': 0.99}]
        result, moves = align_labial_edges(rows, events)
        self.assertEqual(result, rows)
        self.assertEqual(moves, [])

    def test_malformed_evidence_falls_back_to_current_lab(self):
        rows = [(0, 3_000_000, 'a')]
        result, audit = safe_refine_articulation(rows, [{'time': 0.1}], np.full(300, 0.1), 1000)
        self.assertEqual(result, rows)
        self.assertEqual(audit['fallback'], 'KeyError')

    def test_core_straddling_pause_edge_recovers_vowel_without_shortening_pause(self):
        evidence = frames([(0.1725, 't', 0.99), (0.1925, 'e', 0.98), (0.2125, 'e', 0.67)])
        rows = [(0, 2_000_000, 'pau'), (2_000_000, 3_500_000, 'i'), (3_500_000, 4_000_000, 'N')]
        result, _ = refine_articulation(rows, evidence, np.full(400, 0.1), 1000)
        self.assertEqual(result[0], rows[0])
        self.assertEqual(result[1][2], 'e')

    def test_low_probability_greedy_phone_does_not_abort_other_evidence(self):
        evidence = [{'time': 0.1, 'candidates': {'o': 0.3, 'PAD': 0.2, 'i': 0.1}}]
        events = core_events(evidence)
        self.assertEqual(events[0]['phone'], 'o')
        self.assertFalse(events[0]['coreSupported'])


if __name__ == '__main__':
    unittest.main()

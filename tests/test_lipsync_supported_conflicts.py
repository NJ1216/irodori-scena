"""Prevent transcript forcing, closure damage and unanchored vowel overrides."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_supported_conflicts import resolve_supported_conflicts


class SupportedConflictTests(unittest.TestCase):
    def setUp(self):
        self.rows = [(0, 1_000_000, 'N'), (1_000_000, 2_000_000, 'o'), (2_000_000, 3_000_000, 'pau')]
        self.events = [{'time': 0.08, 'phone': 'd', 'confidence': 0.999},
                       {'time': 0.1, 'phone': 'a', 'confidence': 0.999},
                       {'time': 0.2, 'phone': 'y', 'confidence': 0.999}]

    def test_vowel_conflict_corrected_but_closures_and_pauses_unchanged(self):
        result, audit = resolve_supported_conflicts(self.rows, self.events)
        self.assertEqual(result, [self.rows[0], (1_000_000, 1_900_000, 'a'),
                                  (1_900_000, 2_000_000, 'o'), self.rows[-1]])
        self.assertEqual(audit['changes'][0]['before'], 'o')

    def test_low_support_or_missing_context_preserves_baseline(self):
        for events in (self.events[:2], [{**e, 'confidence': 0.8} for e in self.events],
                       [{**self.events[0], 'phone': 'm'}, *self.events[1:]]):
            self.assertEqual(resolve_supported_conflicts(self.rows, events)[0], self.rows)

    def test_short_original_and_short_new_overlap_preserved(self):
        for rows in ([(0, 1_400_000, 'N'), (1_400_000, 2_000_000, 'o')],
                     [(0, 1_000_000, 'N'), (1_000_000, 1_500_000, 'o')]):
            self.assertEqual(resolve_supported_conflicts(rows, self.events)[0], rows)

    def test_no_transcript_can_create_a_proposal(self):
        self.assertEqual(resolve_supported_conflicts(self.rows, [self.events[1]])[0], self.rows)


if __name__ == '__main__':
    unittest.main()

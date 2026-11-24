"""Keep phrase retries local, speech-driven, and confidence-gated."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from lipsync_phrase_recovery import recover_phrases


class PhraseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.rows = [(0, 10_000_000, "i"), (10_000_000, 12_000_000, "pau"),
                     (12_000_000, 20_000_000, "a")]
        self.audio = np.full(2000, 0.1)

    def test_retry_only_uncovered_phrase_and_preserve_existing_events(self):
        calls = []
        existing = [{"time": 1.5, "phone": "a", "confidence": 0.99}]

        def recognize(audio, rate):
            calls.append(len(audio) / rate)
            return [{"time": 0.75, "phone": "o", "confidence": 0.99}]

        events, attempts = recover_phrases(existing, self.rows, self.audio, 1000, recognize)
        self.assertEqual(calls, [1.1])
        self.assertEqual(events, [{"time": 0.75, "phone": "o", "confidence": 0.99}, *existing])
        self.assertEqual(len(attempts), 1)

    def test_no_retry_without_phrase_split_or_without_speech(self):
        def fail(*_):
            self.fail("Unexpected recognition call")
        for rows, audio in (([(0, 20_000_000, "i")], self.audio),
                            (self.rows, np.zeros(2000))):
            events, attempts = recover_phrases([], rows, audio, 1000, fail)
            self.assertEqual((events, attempts), ([], []))

    def test_weak_retry_is_not_applied_and_times_are_local_to_phrase(self):
        existing = [{"time": 0.5, "phone": "a", "confidence": 0.99}]
        events, attempts = recover_phrases(existing, self.rows, self.audio, 1000, lambda *_: [
            {"time": 0.1, "phone": "i", "confidence": 0.5},
            {"time": 0.2, "phone": "o", "confidence": 0.99}])
        self.assertEqual(len(events), 2)
        self.assertAlmostEqual(events[1]["time"], 1.3)
        self.assertEqual(len(attempts[0]["added"]), 1)


class LocalRecoveryTests(unittest.TestCase):
    def test_partial_gap_in_supported_phrase_and_two_retry_limit(self):
        from lipsync_phrase_recovery import recover_local
        rows = [(0, 10_000_000, "i")]
        events = [{"time": 0.85, "phone": "e", "confidence": 0.99}]
        calls = []
        result, attempts = recover_local(events, rows, np.full(1000, 0.1), 1000,
                                         lambda audio, rate: calls.append(len(audio)) or [])
        self.assertEqual(result, events)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(calls), 2)

    def test_absolute_time_and_conflicting_existing_evidence(self):
        from lipsync_phrase_recovery import recover_local
        rows = [(0, 5_000_000, "pau"), (5_000_000, 12_000_000, "i")]
        existing = [{"time": 0.9, "phone": "k", "confidence": 0.99}]
        result, attempts = recover_local(existing, rows, np.full(1200, 0.1), 1000, lambda *_: [
            {"time": 0.3, "phone": "a", "confidence": 0.99},
            {"time": 0.6, "phone": "o", "confidence": 0.99}])
        self.assertAlmostEqual(result[0]["time"], 0.6)
        self.assertEqual(len(result), 2)
        self.assertEqual(len(attempts), 1)

    def test_quiet_and_closed_mouth_never_trigger_retry(self):
        from lipsync_phrase_recovery import recover_local
        def fail(*_):
            self.fail("Protected audio must not be reanalyzed")
        for rows, audio in (([(0, 10_000_000, "N")], np.full(1000, 0.1)),
                            ([(0, 10_000_000, "pau")], np.full(1000, 0.1)),
                            ([(0, 10_000_000, "a")], np.zeros(1000))):
            self.assertEqual(recover_local([], rows, audio, 1000, fail), ([], []))

    def test_failed_recognizer_preserves_baseline(self):
        from lipsync_phrase_recovery import recover_local
        def fail(*_):
            raise Exception("bad inference")
        result, attempts = recover_local([], [(0, 10_000_000, "a")], np.full(1000, 0.1), 1000, fail)
        self.assertEqual(result, [])
        self.assertEqual(len(attempts), 2)
        self.assertTrue(all(a["reason"] == "recognizer_failure" for a in attempts))


class RecordingEdgeTests(unittest.TestCase):
    def test_neutral_context_offset_is_removed_and_negative_events_rejected(self):
        from lipsync_phrase_recovery import recover_local
        calls = []
        def recognize(audio, rate):
            calls.append(len(audio))
            if len(calls) == 1:
                return []
            self.assertTrue(np.all(audio[:400] == 0))
            return [{"time": 0.39, "phone": "a", "confidence": 0.99},
                    {"time": 0.5, "phone": "a", "confidence": 0.99}]
        result, attempts = recover_local([], [(0, 10_000_000, "i")], np.full(1000, 0.1), 1000, recognize)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0]["time"], 0.1)
        self.assertEqual(attempts[-1]["prefixSeconds"], 0.4)


if __name__ == "__main__":
    unittest.main()

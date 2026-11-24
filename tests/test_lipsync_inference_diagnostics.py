"""Lazy frames and prepared-input reuse preserve exact evidence and request ownership."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from lipsync_ctc_probe import LazyEvidence, decode_logits
from lipsync_inference_diagnostics import CandidateRecognizer, DiagnosticRecognizer

SETTINGS = ({'PAD': 0, 'i': 1, 'a': 2}, {'conv_kernel': [1], 'conv_stride': [320]},
            {'do_normalize': False})


class DiagnosticTests(unittest.TestCase):
    def test_lazy_and_eager_evidence_are_exact_including_ties(self):
        logits = np.array([[3, 2, 1], [0, 3, 3]], dtype=np.float32)
        eager = decode_logits(logits, *SETTINGS[:2], with_frames=True)
        lazy = decode_logits(logits, *SETTINGS[:2], with_frames='lazy')
        self.assertIsInstance(lazy, LazyEvidence)
        self.assertEqual(lazy[0], eager[0])
        self.assertIsNone(lazy.frames)
        self.assertEqual(tuple(lazy), eager)
        self.assertIsNone(lazy.probabilities)
        self.assertIs(lazy[1], lazy[1])

    def recognizer(self, *, cache=True, identity=None):
        session = Mock()
        session.run.return_value = [np.array([[[3, 2, 1], [0, 3, 2]]], dtype=np.float32)]
        return DiagnosticRecognizer(session, SETTINGS, identity or {'model': 'one'}, mode='prepared', cache=cache)

    def test_only_identical_float32_model_input_reuses_and_clear_releases(self):
        recognize = self.recognizer()
        audio = np.full(400, .25, dtype=np.float64)
        first = recognize(audio, 16000)
        self.assertIs(recognize(audio + 1e-12, 16000), first)
        self.assertEqual(recognize.session.run.call_count, 1)
        recognize(audio + .01, 16000)
        recognize(audio, 8000)
        self.assertEqual(recognize.session.run.call_count, 3)
        recognize.clear()
        recognize(audio, 16000)
        self.assertEqual(recognize.session.run.call_count, 4)

    def test_cache_disabled_is_exact_and_stage_is_restored_on_exception(self):
        cached, uncached = self.recognizer(), self.recognizer(cache=False)
        audio = np.ones(400)
        for _ in range(2):
            self.assertEqual(tuple(cached(audio, 16000)), tuple(uncached(audio, 16000)))
        self.assertEqual(uncached.session.run.call_count, 2)
        with self.assertRaises(ValueError), uncached.phase('local'):
            uncached(audio, 16000)
            raise ValueError('failed attempt')
        self.assertEqual(uncached.stage, 'full')
        self.assertEqual(uncached.calls[-1]['stage'], 'local')

    def test_model_and_execution_settings_change_cache_identity(self):
        one = self.recognizer(identity={'model': 'one', 'runtime': '1.20.1', 'spin': True})
        two = self.recognizer(identity={'model': 'one', 'runtime': '1.20.1', 'spin': False})
        three = self.recognizer(identity={'model': 'two', 'runtime': '1.20.1', 'spin': True})
        self.assertEqual(len({one.identity_hash, two.identity_hash, three.identity_hash}), 3)

    def test_uninstrumented_candidates_have_exact_evidence_without_recording_calls(self):
        diagnostic = self.recognizer()
        audio = np.full(400, .25)
        for mode in ('lazy', 'prepared'):
            lean = CandidateRecognizer(diagnostic.session, SETTINGS, diagnostic.identity, mode=mode)
            for _ in range(2):
                self.assertEqual(tuple(lean(audio, 16000)), tuple(diagnostic(audio, 16000)))
            self.assertEqual(lean.calls, [])
            self.assertEqual(lean.stages, {})
            lean.clear()
            self.assertEqual(lean.cache, {})


if __name__ == '__main__':
    unittest.main()

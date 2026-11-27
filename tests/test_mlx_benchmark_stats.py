import scena_test_isolation  # noqa: F401
import math
import unittest

from tools.mlx_benchmark_stats import pcm_sha256, snr_db, summarize


class SummarizeTest(unittest.TestCase):
    def test_median_and_p95_of_odd_sample(self):
        summary = summarize([1, 2, 3, 4, 100])
        self.assertEqual(summary["median"], 3)
        self.assertEqual(summary["p95"], 100)
        self.assertEqual(summary["runs"], 5)

    def test_rejects_empty_sample(self):
        with self.assertRaises(ValueError):
            summarize([])


class AudioComparisonTest(unittest.TestCase):
    def test_identical_audio_has_infinite_snr(self):
        self.assertEqual(snr_db([0.5, -0.25, 0.1], [0.5, -0.25, 0.1]), math.inf)

    def test_snr_of_ten_percent_error_is_twenty_db(self):
        self.assertAlmostEqual(snr_db([1.0, 0.0], [0.9, 0.0]), 20.0, places=3)

    def test_length_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            snr_db([1.0, 0.0], [1.0])

    def test_pcm_hash_changes_with_one_sample(self):
        base = [0.1, 0.2, 0.3]
        self.assertEqual(pcm_sha256(base), pcm_sha256(list(base)))
        self.assertNotEqual(pcm_sha256(base), pcm_sha256([0.1, 0.2, 0.31]))


if __name__ == "__main__":
    unittest.main()


class MeasureCaseVarySeedTest(unittest.TestCase):
    """A retake check must compare every seed, not only the first pair."""

    def measure(self, candidate_audio):
        from unittest.mock import patch
        from types import SimpleNamespace

        from tools import benchmark_mlx_tts as bench

        seen = {"baseline": [], "candidate": []}

        def side(name, audio):
            def call(kwargs):
                seen[name].append(kwargs["rng_seed"])
                return SimpleNamespace(audio=audio(kwargs["rng_seed"]))
            return call

        with patch.object(bench, "reset_peak_memory", lambda: None), patch.object(bench, "peak_memory", lambda: None), \
                patch.object(bench, "load_snapshot", lambda: {"loadavg1": 0.0, "otherCpuPercent": 0.0}):
            row = bench.measure_case(side("baseline", lambda seed: [seed * 0.001]), side("candidate", candidate_audio),
                                     {"rng_seed": 100}, 4, 0, vary_seed=True)
        return row, seen

    def test_each_pair_uses_its_own_seed_on_both_sides(self):
        row, seen = self.measure(lambda seed: [seed * 0.001])
        self.assertEqual(seen["baseline"], [100, 101, 102, 103])
        self.assertEqual(seen["candidate"], [100, 101, 102, 103])
        self.assertTrue(row["pcmIdentical"])
        self.assertEqual(row["pairsCompared"], 4)

    def test_a_mismatch_in_a_later_pair_is_reported(self):
        row, _seen = self.measure(lambda seed: [seed * 0.001 if seed != 102 else 0.5])
        self.assertFalse(row["pcmIdentical"])
        self.assertEqual(row["mismatchedSeeds"], [102])

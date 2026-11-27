from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest

from server.modules.direction_optimization import direction_evidence_passes


class DirectionOptimizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = {
            "chunkSize": 10,
            "sampleCount": 30,
            "medianSeconds": 100,
            "p95Seconds": 140,
            "ownershipErrors": 0,
            "constraintViolations": 0,
            "completionRate": 1.0,
            "validFieldAcceptanceRate": 0.98,
            "qualityNonDegraded": True,
        }

    def test_accepts_only_a_complete_non_degrading_speedup(self) -> None:
        candidate = {
            **self.baseline,
            "chunkSize": 50,
            "medianSeconds": 89,
            "p95Seconds": 138,
            "validFieldAcceptanceRate": 0.97,
        }
        self.assertTrue(direction_evidence_passes(candidate, self.baseline))

    def test_rejects_quality_or_tail_latency_regressions(self) -> None:
        candidate = {**self.baseline, "chunkSize": 100, "medianSeconds": 80}
        for field, value in (
            ("sampleCount", 29),
            ("p95Seconds", 141),
            ("ownershipErrors", 1),
            ("constraintViolations", 1),
            ("completionRate", 0.99),
            ("validFieldAcceptanceRate", 0.969),
            ("qualityNonDegraded", False),
        ):
            with self.subTest(field=field):
                self.assertFalse(direction_evidence_passes({**candidate, field: value}, self.baseline))


if __name__ == "__main__":
    unittest.main()

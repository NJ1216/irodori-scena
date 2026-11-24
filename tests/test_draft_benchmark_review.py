from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.build_draft_blind_review import build
from tools.compare_draft_duration_benchmark import compare


def _report(variant: str, *, inputs: int, calls: int, characters: int) -> dict:
    return {"variant": variant, "dialogueCalls": calls, "acceptedCharacters": characters,
            "theme": "三人が閉館前の図書館で手紙を見つける。", "llmCallsIncludingPlanning": calls + 1,
            "targetReached": characters >= 1800, "allSourcesCompleted": True,
            "ownershipErrors": 0, "fallbackUsed": False,
            "quality": {"exactDuplicateLines": 0, "directionCoverage": 1.0, "lineCount": 1},
            "job": {"tokenUsage": {"inputTokens": inputs}, "partialReason": ""},
            "savedProject": {"characters": [{"id": "a", "name": "A"}],
                "scenes": [{"lines": [{"characterId": "a", "text": "本文", "stageDirection": "静かに"}]}]}}


class DraftBenchmarkReviewTests(unittest.TestCase):
    def test_numeric_gate_requires_token_and_call_reductions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, adaptive = root / "base.json", root / "adaptive.json"
            baseline.write_text(json.dumps(_report("baseline", inputs=1000, calls=10, characters=1900)))
            adaptive.write_text(json.dumps(_report("adaptive", inputs=650, calls=6, characters=2000)))
            result = compare("5分", baseline, adaptive)
            self.assertTrue(result["passed"])

    def test_blind_page_hides_variants_and_writes_key_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, adaptive, output = root / "base.json", root / "adaptive.json", root / "review.html"
            baseline.write_text(json.dumps(_report("baseline", inputs=1000, calls=10, characters=1900)))
            adaptive.write_text(json.dumps(_report("adaptive", inputs=650, calls=6, characters=2000)))
            build([("5分", baseline, adaptive)], output, 42)
            page = output.read_text()
            self.assertNotIn("baseline", page)
            self.assertNotIn("adaptive", page)
            self.assertIn("台本 A", page)
            self.assertIn("共通テーマ", page)
            self.assertIn("data-show", page)
            self.assertIn("localStorage", page)
            self.assertIn("blind-review.json", page)
            self.assertTrue((root / "blind-key.json").is_file())

    def test_report_keeps_common_theme_cost_outside_method_difference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, adaptive, fixture = root / "base.json", root / "adaptive.json", root / "fixture.json"
            baseline.write_text(json.dumps(_report("baseline", inputs=1000, calls=10, characters=1900)))
            adaptive.write_text(json.dumps(_report("adaptive", inputs=650, calls=6, characters=2000)))
            fixture.write_text(json.dumps({"themeCalls": 1, "themeUsage": {"totalTokens": 250}}))
            result = compare("5分", baseline, adaptive, fixture)
            self.assertEqual(result["commonThemeCost"]["calls"], 1)
            self.assertEqual(result["methodCosts"]["baseline"]["endToEndCallsIncludingCommonTheme"], 12)
            self.assertEqual(result["methodCosts"]["adaptive"]["endToEndTokensIncludingCommonTheme"], 250)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Compare paired persisted-script reports and apply the numeric benchmark gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _percent(before: int | float, after: int | float) -> float:
    return round((before - after) / max(1, before) * 100, 2)


def compare(label: str, baseline_path: Path, adaptive_path: Path,
            fixture_path: Path | None = None) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    adaptive = json.loads(adaptive_path.read_text(encoding="utf-8"))
    base_usage, candidate_usage = baseline["job"]["tokenUsage"], adaptive["job"]["tokenUsage"]
    input_reduction = _percent(base_usage["inputTokens"], candidate_usage["inputTokens"])
    call_reduction = _percent(baseline["dialogueCalls"], adaptive["dialogueCalls"])
    base_quality, candidate_quality = baseline["quality"], adaptive["quality"]
    gates = {
        "inputTokensReduced30Percent": input_reduction >= 30,
        "dialogueCallsReduced40Percent": call_reduction >= 40,
        "dialogueCallsDidNotIncrease": adaptive["dialogueCalls"] <= baseline["dialogueCalls"],
        "targetReached": adaptive["targetReached"],
        "allSourcesCompleted": adaptive["allSourcesCompleted"],
        "noOwnershipErrors": adaptive["ownershipErrors"] == 0,
        "noPartialOrFallback": (
            not adaptive["fallbackUsed"] and not adaptive["job"].get("partialReason")
            and int(adaptive["job"].get("failedDialogueCalls", 0)) == 0
            and adaptive.get("status", "completed") == "completed"
        ),
        "duplicatesNoWorse": candidate_quality["exactDuplicateLines"] <= base_quality["exactDuplicateLines"],
        "directionCoverageNoWorse": candidate_quality["directionCoverage"] >= base_quality["directionCoverage"],
    }
    theme = json.loads(fixture_path.read_text(encoding="utf-8")) if fixture_path else {}
    theme_usage = theme.get("themeUsage", {})
    common_calls = int(theme.get("themeCalls", 0))
    common_tokens = int(theme_usage.get("totalTokens", 0))
    methods = {}
    for name, report, usage in (("baseline", baseline, base_usage),
                                ("adaptive", adaptive, candidate_usage)):
        methods[name] = {
            "inputTokens": int(usage.get("inputTokens", 0)),
            "outputTokens": int(usage.get("outputTokens", 0)),
            "planningAndDialogueCalls": int(report.get("llmCallsIncludingPlanning", 0)),
            "dialogueCalls": int(report.get("dialogueCalls", 0)),
            "endToEndCallsIncludingCommonTheme": int(report.get("llmCallsIncludingPlanning", 0)) + common_calls,
            "endToEndTokensIncludingCommonTheme": int(usage.get("totalTokens", 0)) + common_tokens,
        }
    return {"fixture": label, "themeFixture": theme,
            "commonThemeCost": {"calls": common_calls, "tokenUsage": theme_usage},
            "methodCosts": methods, "inputTokenReductionPercent": input_reduction,
            "dialogueCallReductionPercent": call_reduction, "gates": gates,
            "passed": all(gates.values()), "baseline": baseline, "adaptive": adaptive}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", action="append", nargs=4,
                        metavar=("LABEL", "FIXTURE", "BASELINE", "ADAPTIVE"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    comparisons = [compare(label, Path(base), Path(candidate), Path(fixture))
                   for label, fixture, base, candidate in args.pair]
    report = {"passed": all(item["passed"] for item in comparisons), "comparisons": comparisons}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "comparisons": [{
        "fixture": item["fixture"], "passed": item["passed"],
        "inputTokenReductionPercent": item["inputTokenReductionPercent"],
        "dialogueCallReductionPercent": item["dialogueCallReductionPercent"],
    } for item in comparisons]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

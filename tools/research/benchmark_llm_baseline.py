#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def _number(record: dict[str, Any], key: str) -> float | None:
    value = record.get(key)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    keys = ("totalTokens", "promptTokens", "completionTokens", "cachedTokens",
            "uncachedInputTokens", "llmCalls")
    sums = {key: sum(value for record in records if (value := _number(record, key)) is not None)
            for key in keys}
    prefills = [value for record in records if (value := _number(record, "prefillSeconds")) is not None]
    hits = [bool(record["kvCacheHit"]) for record in records if isinstance(record.get("kvCacheHit"), bool)]

    def weighted(key: str) -> float | None:
        eligible = [record for record in records if _number(record, key) is not None]
        if not eligible:
            return None
        weight = sum(float(record.get("weight", 1)) for record in eligible)
        return sum(float(record[key]) * float(record.get("weight", 1)) for record in eligible) / weight

    return {
        **{key: int(value) for key, value in sums.items()},
        "medianPrefillSeconds": statistics.median(prefills) if prefills else None,
        "kvCacheHitRate": sum(hits) / len(hits) if hits else None,
        "validFieldAcceptanceRate": weighted("validFieldAcceptanceRate"),
        "completionRate": weighted("completionRate"),
        "ownershipErrors": sum(int(record.get("ownershipErrors", 0)) for record in records),
        "constraintViolations": sum(int(record.get("constraintViolations", 0)) for record in records),
        "majorQualityOmissions": sum(int(record.get("majorQualityOmissions", 0)) for record in records),
        "qualityNonDegradedRate": weighted("qualityNonDegradedRate"),
        "sampleCount": len(records),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare the production LLM baseline with an experimental candidate.")
    parser.add_argument("input", type=Path, help="JSONL records with feature and variant=baseline/candidate")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    report = {"features": []}
    for feature in sorted({str(record["feature"]) for record in records}):
        report["features"].append({
            "feature": feature,
            "baseline": aggregate([row for row in records if row["feature"] == feature and row["variant"] == "baseline"]),
            "candidate": aggregate([row for row in records if row["feature"] == feature and row["variant"] == "candidate"]),
        })
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()


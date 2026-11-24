#!/usr/bin/env python3
"""Orchestrate fresh 5/30/60 minute baseline/adaptive production comparisons."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = {5: ("baseline", "adaptive"), 30: ("adaptive", "baseline"), 60: ("baseline", "adaptive")}


def _run(command: list[str], cwd: Path, *, code_root: Path | None = None) -> None:
    environment = dict(os.environ)
    if code_root is not None:
        environment["SCENA_BENCHMARK_CODE_ROOT"] = str(code_root)
        environment["SCENA_DATA_ROOT"] = str(ROOT / "scena-data")
    subprocess.run(command, cwd=cwd, check=True, env=environment)  # noqa: S603


def _revision(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--baseline-seed-patch", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    patch_bytes = args.baseline_seed_patch.read_bytes()
    metadata = {
        "baselineCommit": _revision(args.baseline_root), "adaptiveCommit": _revision(ROOT),
        "baselineSeedPatch": str(args.baseline_seed_patch.resolve()),
        "baselineSeedPatchSha256": hashlib.sha256(patch_bytes).hexdigest(),
        "seed": args.seed, "executionOrder": ORDER,
    }
    pairs = []
    for minutes, variants in ORDER.items():
        fixture = output / f"{minutes}m-theme.json"
        _run([sys.executable, str(ROOT / "tools/generate_draft_theme_fixture.py"),
              "--minutes", str(minutes), "--seed", str(args.seed), "--output", str(fixture)], ROOT)
        for variant in variants:
            worktree = args.baseline_root if variant == "baseline" else ROOT
            destination = output / f"{minutes}m-{variant}"
            _run([sys.executable, str(ROOT / "tools/benchmark_production_draft.py"),
                  "--variant", variant, "--fixture", str(fixture), "--output", str(destination),
                  "--global-characters", str(ROOT / "scena-data/global-characters/characters.json")],
                 worktree, code_root=worktree)
        pairs.append((f"{minutes}分", fixture, output / f"{minutes}m-baseline/report.json",
                      output / f"{minutes}m-adaptive/report.json"))
    compare_command = [sys.executable, str(ROOT / "tools/compare_draft_duration_benchmark.py")]
    for label, fixture, baseline, adaptive in pairs:
        compare_command.extend(["--pair", label, str(fixture), str(baseline), str(adaptive)])
    comparison_path = output / "comparison.json"
    compare_command.extend(["--output", str(comparison_path)])
    _run(compare_command, ROOT)
    comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
    comparison["benchmarkMetadata"] = metadata
    comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if comparison["passed"]:
        command = [sys.executable, str(ROOT / "tools/build_draft_blind_review.py")]
        for label, _, baseline, adaptive in pairs:
            command.extend(["--fixture", label, str(baseline), str(adaptive)])
        command.extend(["--output", str(output / "blind-review.html"), "--seed", str(args.seed)])
        _run(command, ROOT)
    print(json.dumps({"passed": comparison["passed"], "output": str(output),
                      "blindReviewGenerated": comparison["passed"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

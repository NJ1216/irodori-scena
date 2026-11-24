"""Run external optimization candidates with reproducible evidence capture."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import random
import statistics
import subprocess
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

from tools.optimization_evidence import (
    CandidateConfig,
    abba_order,
    drift_assessment,
    environment_manifest,
    result_evidence,
    sha256_manifest,
    write_sha256_manifest,
)


def percentile(values: Sequence[float], percent: float) -> float:
    if not values:
        raise ValueError("percentile requires values")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percent / 100 * len(ordered)) - 1)]


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_variant = {
        variant: [float(row["wallClockSeconds"]) for row in rows if row["variant"] == variant and row["success"]]
        for variant in ("baseline", "candidate")
    }
    if not all(by_variant.values()):
        return {"valid": False, "reason": "missing-successful-variant"}
    baseline_median = statistics.median(by_variant["baseline"])
    candidate_median = statistics.median(by_variant["candidate"])
    improvement = (baseline_median - candidate_median) / baseline_median * 100
    return {
        "valid": all(row["success"] for row in rows),
        "runsPerVariant": {key: len(value) for key, value in by_variant.items()},
        "baseline": {"medianSeconds": baseline_median, "p95Seconds": percentile(by_variant["baseline"], 95)},
        "candidate": {"medianSeconds": candidate_median, "p95Seconds": percentile(by_variant["candidate"], 95)},
        "medianImprovementPercent": improvement,
    }


def matrix_order(config: CandidateConfig, repetitions: int) -> list[dict[str, Any]]:
    return [
        {"fixture": fixture, "seed": seed, "variant": variant}
        for fixture in config.fixtures
        for seed in config.seeds
        for variant in abba_order(repetitions * 2)
    ]


def should_escalate(summary: dict[str, Any], threshold: float, margin: float) -> bool:
    improvement = summary.get("medianImprovementPercent")
    return bool(summary.get("valid") and isinstance(improvement, (int, float)) and abs(improvement - threshold) <= margin)


def improvement_confidence_interval(rows: Sequence[dict[str, Any]], samples: int = 1000) -> tuple[float, float]:
    baseline = [float(row["wallClockSeconds"]) for row in rows if row["variant"] == "baseline" and row["success"]]
    candidate = [float(row["wallClockSeconds"]) for row in rows if row["variant"] == "candidate" and row["success"]]
    if not baseline or not candidate:
        return float("-inf"), float("inf")
    generator = random.Random(0)
    improvements = []
    for _ in range(samples):
        baseline_median = statistics.median(generator.choices(baseline, k=len(baseline)))
        candidate_median = statistics.median(generator.choices(candidate, k=len(candidate)))
        improvements.append((baseline_median - candidate_median) / baseline_median * 100)
    return percentile(improvements, 2.5), percentile(improvements, 97.5)


def cases_needing_escalation(rows: Sequence[dict[str, Any]], threshold: float, margin: float) -> list[dict[str, Any]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row["fixture"]), int(row["seed"])), []).append(row)
    cases = []
    for (fixture, seed), case_rows in groups.items():
        summary = summarize(case_rows)
        improvement = summary.get("medianImprovementPercent")
        lower, upper = improvement_confidence_interval(case_rows)
        near_threshold = isinstance(improvement, (int, float)) and abs(improvement - threshold) <= margin
        crosses_no_improvement = lower <= 0 <= upper
        if summary.get("valid") and (near_threshold or crosses_no_improvement):
            cases.append({"fixture": fixture, "seed": seed, "nearThreshold": near_threshold,
                          "confidenceInterval": [lower, upper], "crossesNoImprovement": crosses_no_improvement})
    return cases


def environment_matches(before: dict[str, Any], after: dict[str, Any]) -> bool:
    fields = set(before) | set(after)
    fields.discard("capturedAt")
    return all(before.get(field) == after.get(field) for field in fields)


def evidence_run_complete(root: Path) -> bool:
    marker = root / "complete.json"
    manifest_path = root / "sha256-manifest.json"
    if not marker.is_file() or not manifest_path.is_file():
        return False
    try:
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    identity_matches = (
        marker_data.get("candidateId") == root.parent.name
        and marker_data.get("runId") == root.name
    )
    return identity_matches and recorded == sha256_manifest(root)


def resolve_commit(repository: Path, revision: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def worktree_status(worktree: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(worktree), "status", "--short"], capture_output=True, text=True, check=False,
    )
    return result.stdout if result.returncode == 0 else None


def validate_worktrees(
    worktrees: dict[str, Path], commits: dict[str, str], fixtures: Sequence[str],
) -> dict[str, dict[str, Any]]:
    if worktrees["baseline"] == worktrees["candidate"]:
        raise ValueError("baseline and candidate worktrees must be distinct")
    for variant, worktree in worktrees.items():
        if resolve_commit(worktree, "HEAD") != commits[variant]:
            raise ValueError(f"{variant} worktree HEAD does not match configured commit")
        if worktree_status(worktree) != "":
            raise ValueError(f"{variant} worktree must be clean")
    metadata = {}
    for fixture in fixtures:
        relative = Path(fixture)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("fixtures must be repository-relative paths")
        paths = {variant: (worktree / relative).resolve() for variant, worktree in worktrees.items()}
        payloads = {variant: path.read_bytes() for variant, path in paths.items() if path.is_file()}
        if len(payloads) != 2 or payloads["baseline"] != payloads["candidate"]:
            raise ValueError(f"fixture differs between worktrees: {fixture}")
        metadata[fixture] = {"sha256": hashlib.sha256(payloads["baseline"]).hexdigest(),
                             "bytes": payloads["baseline"]}
    return metadata


def validate_output_path(repository: Path, output: Path, candidate_id: str) -> None:
    expected = (repository / "artifacts" / "optimization" / candidate_id).resolve()
    resolved = output.resolve()
    if resolved.parent != expected or not resolved.name:
        raise ValueError("output must be artifacts/optimization/<candidate-id>/<run-id>")


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def child_memory_evidence(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"available": False, "error": "child did not write mps-memory.json"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        current, peak = payload["currentBytes"], payload["peakBytes"]
        if type(current) is not int or type(peak) is not int:
            raise TypeError("currentBytes and peakBytes must be integers")
        if current < 0 or peak < current:
            raise ValueError("peakBytes must be at least currentBytes and both must be non-negative")
        return {"available": True, "currentBytes": current, "peakBytes": peak}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return {"available": False, "error": f"invalid child memory evidence: {error}"}


def canonical_result_hash(structured: object) -> tuple[dict[str, Any] | None, str | None]:
    canonical = structured.get("canonicalResult") if isinstance(structured, dict) else None
    if not isinstance(canonical, dict):
        return None, None
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return canonical, hashlib.sha256(payload.encode()).hexdigest()


def run_once(
    variant: str,
    ordinal: int,
    command: Sequence[str],
    output: Path,
    require_mps_memory: bool,
    *,
    fixture: str,
    fixture_path: Path,
    fixture_sha256: str,
    seed: int,
    expected_commit: str,
    worktree: Path,
) -> dict[str, Any]:
    run_dir = output / "runs" / f"{ordinal:03d}-{variant}"
    run_dir.mkdir(parents=True)
    started_at = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    environment = os.environ.copy()
    environment.update({
        "SCENA_OPTIMIZATION_RUN_DIR": str(run_dir.resolve()),
        "SCENA_OPTIMIZATION_VARIANT": variant,
        "SCENA_OPTIMIZATION_ORDINAL": str(ordinal),
        "SCENA_OPTIMIZATION_MEMORY_PATH": str((run_dir / "mps-memory.json").resolve()),
        "SCENA_OPTIMIZATION_FIXTURE": str(fixture_path),
        "SCENA_OPTIMIZATION_SEED": str(seed),
        "SCENA_OPTIMIZATION_EXPECTED_COMMIT": expected_commit,
    })
    commit_before = resolve_commit(worktree, "HEAD")
    status_before = worktree_status(worktree)
    if commit_before == expected_commit and status_before == "":
        result = subprocess.run(command, cwd=worktree, capture_output=True, check=False, env=environment)
    else:
        result = subprocess.CompletedProcess(command, 125, b"", b"worktree precondition failed\n")
    commit_after = resolve_commit(worktree, "HEAD")
    status_after = worktree_status(worktree)
    elapsed = time.perf_counter() - started
    (run_dir / "stdout.bin").write_bytes(result.stdout)
    (run_dir / "stderr.bin").write_bytes(result.stderr)
    memory = child_memory_evidence(run_dir / "mps-memory.json")
    result_path = run_dir / "result.json"
    wav_paths = sorted(run_dir.rglob("*.wav"))
    try:
        structured = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        structured = None
    child_commit_matches = isinstance(structured, dict) and structured.get("executedCommit") == expected_commit
    worktree_commit_matches = commit_before == expected_commit and commit_after == expected_commit
    worktree_clean = status_before == "" and status_after == ""
    canonical, canonical_hash = canonical_result_hash(structured)
    commit_matches = child_commit_matches and worktree_commit_matches
    required_outputs = isinstance(canonical, dict) and bool(wav_paths)
    row = {
        "ordinal": ordinal,
        "variant": variant,
        "fixture": fixture,
        "fixtureArtifact": str(fixture_path),
        "fixtureSha256": fixture_sha256,
        "seed": seed,
        "expectedCommit": expected_commit,
        "command": list(command),
        "startedAt": started_at,
        "wallClockSeconds": elapsed,
        "exitCode": result.returncode,
        "success": bool(
            result.returncode == 0 and required_outputs and commit_matches and worktree_clean
            and (not require_mps_memory or memory["available"])
        ),
        "commitMatches": commit_matches,
        "childCommitMatches": child_commit_matches,
        "worktreeCommitBefore": commit_before,
        "worktreeCommitAfter": commit_after,
        "worktreeStatusBefore": status_before,
        "worktreeStatusAfter": status_after,
        "worktreeClean": worktree_clean,
        "canonicalResult": canonical,
        "canonicalResultSha256": canonical_hash,
        "requiredOutputsPresent": required_outputs,
        "mpsMemory": memory if require_mps_memory or memory["available"] else None,
        "outputs": [
            result_evidence(path, run_dir) for path in sorted(run_dir.rglob("*"))
            if path.is_file() and path.name != "run.json"
        ],
    }
    (run_dir / "run.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return row


def pcm_equality(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, int], list[tuple[str, tuple[str, ...]]]] = {}
    for row in rows:
        hashes = tuple(sorted(
            str(item["pcmSha256"]) for item in row.get("outputs", []) if "pcmSha256" in item
        ))
        groups.setdefault((str(row["fixture"]), int(row["seed"])), []).append((str(row["variant"]), hashes))
    mismatches = []
    for (fixture, seed), values in groups.items():
        baseline = {hashes for variant, hashes in values if variant == "baseline"}
        candidate = {hashes for variant, hashes in values if variant == "candidate"}
        if len(baseline) != 1 or baseline != candidate or not next(iter(baseline), ()):
            mismatches.append({"fixture": fixture, "seed": seed})
    return {"valid": not mismatches, "mismatches": mismatches}


def canonical_result_equality(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, int], list[tuple[str, str | None]]] = {}
    for row in rows:
        groups.setdefault((str(row["fixture"]), int(row["seed"])), []).append(
            (str(row["variant"]), row.get("canonicalResultSha256")))
    mismatches = []
    for (fixture, seed), values in groups.items():
        baseline = {digest for variant, digest in values if variant == "baseline"}
        candidate = {digest for variant, digest in values if variant == "candidate"}
        if len(baseline) != 1 or baseline != candidate or None in baseline:
            mismatches.append({"fixture": fixture, "seed": seed})
    return {"valid": not mismatches, "mismatches": mismatches}


def acceptance_gates(summary: dict[str, Any], rows: Sequence[dict[str, Any]], config: CandidateConfig,
                     improvement_threshold: float) -> dict[str, Any]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((str(row["fixture"]), int(row["seed"])), []).append(row)
    performance_cases = []
    for (fixture, seed), case_rows in groups.items():
        case = summarize(case_rows)
        median = float(case.get("medianImprovementPercent", float("-inf")))
        baseline_p95 = float(case.get("baseline", {}).get("p95Seconds", float("inf")))
        candidate_p95 = float(case.get("candidate", {}).get("p95Seconds", float("inf")))
        performance_cases.append({"fixture": fixture, "seed": seed,
                                  "medianImprovementPercent": median,
                                  "baselineP95Seconds": baseline_p95,
                                  "candidateP95Seconds": candidate_p95,
                                  "medianValid": median >= improvement_threshold,
                                  "p95Valid": candidate_p95 < baseline_p95 * 1.05})
    peaks = [int(row["mpsMemory"]["peakBytes"]) for row in rows
             if isinstance(row.get("mpsMemory"), dict) and row["mpsMemory"].get("available")]
    memory_valid = not config.requires_mps_memory or (
        len(peaks) == len(rows) and max(peaks, default=0) <= int(config.memory_ceiling_bytes or 0)
    )
    return {"medianValid": bool(performance_cases) and all(case["medianValid"] for case in performance_cases),
            "p95Valid": bool(performance_cases) and all(case["p95Valid"] for case in performance_cases),
            "memoryValid": memory_valid, "memoryCeilingBytes": config.memory_ceiling_bytes,
            "peakMemoryBytes": max(peaks, default=None), "performanceCases": performance_cases}


def drift_by_case(rows: Sequence[dict[str, Any]], limit_percent: float) -> dict[str, Any]:
    groups: dict[tuple[str, int], list[float]] = {}
    for row in rows:
        if row["variant"] == "baseline":
            groups.setdefault((str(row["fixture"]), int(row["seed"])), []).append(row["wallClockSeconds"])
    cases = []
    for (fixture, seed), timings in groups.items():
        assessment = drift_assessment(timings[0], timings[-1], limit_percent)
        cases.append({"fixture": fixture, "seed": seed, **assessment})
    return {"valid": bool(cases) and all(case["valid"] for case in cases), "cases": cases}


def validate_run_inputs(
    args: argparse.Namespace, config: CandidateConfig,
) -> tuple[dict[str, str], dict[str, Path], dict[str, dict[str, Any]]]:
    if not args.provider.strip():
        raise ValueError("provider is required")
    if args.engine is None or not args.engine.is_dir():
        raise ValueError("engine must identify the external engine checkout")
    output = args.output
    validate_output_path(args.repository, output, config.candidate_id)
    model_files = {path.resolve() for path in args.model_file if path.is_file()}
    if config.requires_mps_memory and len(model_files) < 2:
        raise ValueError("MPS candidates require --model-file entries for model and Codec")
    commit_resolution = {
        "baseline": resolve_commit(args.repository, config.baseline_commit),
        "candidate": resolve_commit(args.repository, config.candidate_commit),
    }
    if not all(commit_resolution.values()):
        raise ValueError("baseline and candidate commits must resolve")
    worktrees = {"baseline": args.baseline_worktree.resolve(), "candidate": args.candidate_worktree.resolve()}
    commits = {key: str(value) for key, value in commit_resolution.items()}
    fixture_metadata = validate_worktrees(worktrees, commits, config.fixtures)
    return commits, worktrees, fixture_metadata


def run_suite(args: argparse.Namespace) -> int:
    config = CandidateConfig.load(args.config)
    commit_resolution, worktrees, fixture_metadata = validate_run_inputs(args, config)
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    fixture_artifacts = {}
    for index, fixture in enumerate(config.fixtures, 1):
        destination = output / "fixtures" / f"{index:03d}-{fixture_metadata[fixture]['sha256']}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(fixture_metadata[fixture]["bytes"])
        fixture_artifacts[fixture] = destination.resolve()
    (output / "candidate.json").write_text(json.dumps(vars(config), default=list, ensure_ascii=False, indent=2) + "\n")
    rows: list[dict[str, Any]] = []
    commands = {"baseline": args.baseline_command, "candidate": args.candidate_command}
    with exclusive_lock(args.mps_lock):
        before = environment_manifest(args.repository, args.engine, provider=args.provider, model_files=args.model_file)
        if before["repositoryCommit"] is None or before["engineCommit"] is None or before["engineStatus"] is None:
            raise ValueError("repository and engine must be readable Git checkouts")
        initial_order = matrix_order(config, config.repetitions)
        for ordinal, item in enumerate(initial_order, 1):
            variant = item["variant"]
            rows.append(run_once(variant, ordinal, commands[variant], output, config.requires_mps_memory,
                                 fixture=item["fixture"], fixture_path=fixture_artifacts[item["fixture"]],
                                 fixture_sha256=fixture_metadata[item["fixture"]]["sha256"], seed=item["seed"],
                                 expected_commit=str(commit_resolution[variant]), worktree=worktrees[variant]))
        escalation_cases = cases_needing_escalation(
            rows, args.improvement_threshold, args.escalation_margin)
        if config.max_repetitions > config.repetitions and escalation_cases:
            full_order = matrix_order(config, config.max_repetitions)
            completed = {(row["fixture"], row["seed"], row["variant"]): 0 for row in rows}
            for row in rows:
                key = (row["fixture"], row["seed"], row["variant"])
                completed[key] += 1
            remaining = []
            escalation_keys = {(case["fixture"], case["seed"]) for case in escalation_cases}
            for item in full_order:
                key = (item["fixture"], item["seed"], item["variant"])
                if (item["fixture"], item["seed"]) not in escalation_keys:
                    continue
                if completed.get(key, 0):
                    completed[key] -= 1
                else:
                    remaining.append(item)
            for ordinal, item in enumerate(remaining, len(rows) + 1):
                variant = item["variant"]
                rows.append(run_once(variant, ordinal, commands[variant], output, config.requires_mps_memory,
                                     fixture=item["fixture"], fixture_path=fixture_artifacts[item["fixture"]],
                                     fixture_sha256=fixture_metadata[item["fixture"]]["sha256"], seed=item["seed"],
                                     expected_commit=str(commit_resolution[variant]), worktree=worktrees[variant]))
        after = environment_manifest(args.repository, args.engine, provider=args.provider, model_files=args.model_file)
        engine_unchanged = before["engineCommit"] == after["engineCommit"] and before["engineStatus"] == after["engineStatus"]
        environment_stable = environment_matches(before, after)
        summary = summarize(rows)
        summary["drift"] = drift_by_case(rows, config.drift_limit_percent)
        summary["engineUnchanged"] = engine_unchanged
        summary["environmentStable"] = environment_stable
        summary["configuredCommitResolution"] = commit_resolution
        summary["pcmEquality"] = pcm_equality(rows)
        summary["canonicalResultEquality"] = canonical_result_equality(rows)
        summary["escalationCases"] = escalation_cases
        summary["acceptanceGates"] = acceptance_gates(summary, rows, config, args.improvement_threshold)
        summary["valid"] = bool(summary.get("valid") and summary["drift"]["valid"] and engine_unchanged
            and environment_stable and summary["pcmEquality"]["valid"]
            and summary["canonicalResultEquality"]["valid"]
            and all(value for key, value in summary["acceptanceGates"].items() if key.endswith("Valid")))
        (output / "environment-before.json").write_text(json.dumps(before, ensure_ascii=False, indent=2) + "\n")
        (output / "environment-after.json").write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n")
        (output / "runs.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
        (output / "complete.json").write_text(json.dumps({
            "candidateId": config.candidate_id, "runId": output.name,
            "completedAt": datetime.now(UTC).isoformat(), "valid": summary["valid"], "runCount": len(rows),
        }, ensure_ascii=False, indent=2) + "\n")
        write_sha256_manifest(output)
    return 0 if summary["valid"] else 1


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--config", type=Path, required=True)
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--repository", type=Path, default=Path.cwd())
    value.add_argument("--engine", type=Path, required=True)
    value.add_argument("--provider", required=True)
    value.add_argument("--model-file", type=Path, action="append", default=[])
    value.add_argument("--baseline-command", nargs="+", required=True)
    value.add_argument("--candidate-command", nargs="+", required=True)
    value.add_argument("--baseline-worktree", type=Path, required=True)
    value.add_argument("--candidate-worktree", type=Path, required=True)
    value.add_argument("--mps-lock", type=Path, default=Path("/tmp/irodori-scena-mps.lock"))
    value.add_argument("--improvement-threshold", type=float, default=5.0)
    value.add_argument("--escalation-margin", type=float, default=1.0)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    return run_suite(parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

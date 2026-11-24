from __future__ import annotations

import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.optimization_runner import (
    acceptance_gates,
    canonical_result_equality,
    canonical_result_hash,
    cases_needing_escalation,
    drift_by_case,
    child_memory_evidence,
    environment_matches,
    evidence_run_complete,
    matrix_order,
    pcm_equality,
    percentile,
    parser,
    run_once,
    should_escalate,
    summarize,
    validate_output_path,
    validate_worktrees,
)
from tools.optimization_evidence import CandidateConfig, write_sha256_manifest
from tools.validate_mps_adapter import MpsPeakTracker


class OptimizationRunnerTests(unittest.TestCase):
    def make_git_fixture(self, root: Path, content: str) -> str:
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "fixture.json").write_text(content)
        subprocess.run(["git", "-C", str(root), "add", "fixture.json"], check=True)
        subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c",
                        "user.email=test@example.invalid", "commit", "-qm", "fixture"], check=True)
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True).stdout.strip()

    def test_mps_tracker_writes_child_owned_peak(self) -> None:
        class Mps:
            values = iter((3, 9, 5))
            def driver_allocated_memory(self):
                return next(self.values, 5)
        with TemporaryDirectory() as directory:
            destination = Path(directory) / "memory.json"
            tracker = MpsPeakTracker(type("Torch", (), {"mps": Mps()})(), destination, interval=60)
            tracker.start()
            tracker.peak = 9
            tracker.stop()
            self.assertEqual(json.loads(destination.read_text()), {"currentBytes": 5, "peakBytes": 9})

    def test_matrix_covers_every_fixture_seed_and_variant(self) -> None:
        config = CandidateConfig("id", "h", "t", "e", "a", "s", "a", "b",
                                 ("one", "two"), (1, 2), repetitions=2, max_repetitions=2)
        rows = matrix_order(config, 2)
        self.assertEqual(len(rows), 16)
        self.assertEqual({(row["fixture"], row["seed"]) for row in rows},
                         {("one", 1), ("one", 2), ("two", 1), ("two", 2)})

    def test_summary_reports_median_p95_and_escalation_boundary(self) -> None:
        rows = [
            {"variant": variant, "wallClockSeconds": value, "success": True}
            for variant, values in (("baseline", [10, 11, 12]), ("candidate", [9, 10, 11]))
            for value in values
        ]
        summary = summarize(rows)
        self.assertEqual(summary["baseline"]["medianSeconds"], 11)
        self.assertEqual(summary["baseline"]["p95Seconds"], 12)
        self.assertEqual(percentile([3, 1, 2], 95), 3)
        self.assertTrue(should_escalate({"valid": True, "medianImprovementPercent": 5.5}, 5, 1))
        self.assertFalse(should_escalate({"valid": True, "medianImprovementPercent": 7}, 5, 1))

    def test_runner_requires_engine_and_provider_arguments(self) -> None:
        with self.assertRaises(SystemExit):
            parser().parse_args([
                "--config", "config.json", "--output", "out",
                "--baseline-command", "true", "--candidate-command", "true",
            ])

    def test_child_memory_evidence_requires_valid_peak(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "mps-memory.json"
            self.assertFalse(child_memory_evidence(path)["available"])
            path.write_text('{"currentBytes":34,"peakBytes":12}')
            self.assertFalse(child_memory_evidence(path)["available"])
            path.write_text('{"currentBytes":12,"peakBytes":34}')
            self.assertEqual(child_memory_evidence(path), {"available": True, "currentBytes": 12, "peakBytes": 34})

    def test_run_once_captures_wall_clock_streams_json_and_memory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            expected_commit = self.make_git_fixture(worktree, '{"text":"fixture"}')
            output = root / "output"
            row = run_once(
                "baseline", 1,
                [sys.executable, "-c", (
                    'import json, os, pathlib, sys, wave; '
                    'root=pathlib.Path(os.environ["SCENA_OPTIMIZATION_RUN_DIR"]); (root/"nested").mkdir(); '
                    'w=wave.open(str(root/"nested"/"sample.wav"),"wb"); w.setnchannels(1); w.setsampwidth(2); '
                    'w.setframerate(8000); w.writeframes(b"\\x01\\x00"*8); w.close(); '
                    'pathlib.Path(os.environ["SCENA_OPTIMIZATION_MEMORY_PATH"]).write_text('
                    'json.dumps({"currentBytes":1,"peakBytes":2})); '
                    'pathlib.Path(root,"result.json").write_text(json.dumps('
                    '{"executedCommit":os.environ["SCENA_OPTIMIZATION_EXPECTED_COMMIT"],'
                    '"canonicalResult":{"text":"same"}})); '
                    'print(os.environ["SCENA_OPTIMIZATION_VARIANT"]); print("note", file=sys.stderr)'
                )],
                output, True, fixture="fixture.json", seed=42,
                fixture_path=worktree / "fixture.json", fixture_sha256="fixture-hash",
                expected_commit=expected_commit, worktree=worktree,
            )
            run_dir = output / "runs" / "001-baseline"
            self.assertTrue(row["success"])
            self.assertGreaterEqual(row["wallClockSeconds"], 0)
            self.assertEqual((run_dir / "stdout.bin").read_text().strip(), "baseline")
            self.assertEqual((run_dir / "stderr.bin").read_text().strip(), "note")
            evidence = {item["path"]: item for item in row["outputs"]}
            self.assertIn("nested/sample.wav", evidence)
            self.assertEqual(evidence["nested/sample.wav"]["pcm"]["sample_width_bytes"], 2)
            self.assertEqual(json.loads((run_dir / "run.json").read_text())["mpsMemory"]["peakBytes"], 2)

    def test_run_once_rejects_missing_pcm_and_mismatched_executed_commit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, "-c", (
                'import json,os,pathlib; root=pathlib.Path(os.environ["SCENA_OPTIMIZATION_RUN_DIR"]); '
                '(root/"result.json").write_text(json.dumps({"executedCommit":"wrong"}))'
            )]
            row = run_once("candidate", 1, command, root, False,
                           fixture="fixture.json", fixture_path=root / "fixture.json",
                           fixture_sha256="fixture-hash", seed=42, expected_commit="a" * 40,
                           worktree=Path(__file__).resolve().parents[1])
            self.assertFalse(row["success"])
            self.assertFalse(row["commitMatches"])
            self.assertFalse(row["requiredOutputsPresent"])

    def test_runner_does_not_trust_child_commit_claim(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            worktree = root / "worktree"
            expected = self.make_git_fixture(worktree, '{"text":"fixture"}')
            output = root / "output"
            command = [sys.executable, "-c", (
                'import json,os,pathlib,wave; root=pathlib.Path(os.environ["SCENA_OPTIMIZATION_RUN_DIR"]); '
                'w=wave.open(str(root/"sample.wav"),"wb"); w.setnchannels(1); w.setsampwidth(2); '
                'w.setframerate(8000); w.writeframes(b"\\x00\\x00"); w.close(); '
                '(root/"result.json").write_text(json.dumps({"executedCommit":'
                'os.environ["SCENA_OPTIMIZATION_EXPECTED_COMMIT"],"canonicalResult":{"ok":True}}))'
            )]
            with patch("tools.optimization_runner.resolve_commit", side_effect=[expected, "f" * 40]):
                row = run_once("candidate", 1, command, output, False, fixture="f",
                               fixture_path=worktree / "fixture.json", fixture_sha256="fixture-hash", seed=1,
                               expected_commit=expected, worktree=worktree)
            self.assertTrue(row["childCommitMatches"])
            self.assertFalse(row["commitMatches"])
            self.assertFalse(row["success"])

    def test_pcm_and_acceptance_gates_fail_closed(self) -> None:
        rows = [
            {"fixture": "f", "seed": 1, "variant": variant, "outputs": [{"pcmSha256": digest}],
             "mpsMemory": {"available": True, "peakBytes": peak}, "success": True}
            for variant, digest, peak in (("baseline", "same", 10), ("candidate", "same", 12))
        ]
        self.assertTrue(pcm_equality(rows)["valid"])
        rows[0]["canonicalResultSha256"] = "same-result"
        rows[1]["canonicalResultSha256"] = "different-result"
        self.assertFalse(canonical_result_equality(rows)["valid"])
        rows[1]["outputs"][0]["pcmSha256"] = "different"
        self.assertFalse(pcm_equality(rows)["valid"])
        config = CandidateConfig("id", "h", "t", "e", "a", "s", "a", "b", ("f",), (1,),
                                 requires_mps_memory=True, memory_ceiling_bytes=11)
        rows[0]["wallClockSeconds"] = 1
        rows[1]["wallClockSeconds"] = 1.1
        gates = acceptance_gates({}, rows, config, 5)
        self.assertEqual((gates["medianValid"], gates["p95Valid"], gates["memoryValid"]),
                         (False, False, False))

    def test_canonical_result_hash_excludes_provenance(self) -> None:
        first = {"canonicalResult": {"text": "same", "value": 1},
                 "executedCommit": "a", "provenance": {"duration": 1}}
        second = {"provenance": {"duration": 99}, "executedCommit": "b",
                  "canonicalResult": {"value": 1, "text": "same"}}
        self.assertEqual(canonical_result_hash(first), canonical_result_hash(second))

    def test_p95_allows_less_than_five_percent_regression(self) -> None:
        rows = [
            {"fixture": "f", "seed": 1, "variant": "baseline", "wallClockSeconds": 10,
             "success": True, "outputs": []},
            {"fixture": "f", "seed": 1, "variant": "candidate", "wallClockSeconds": 10.49,
             "success": True, "outputs": []},
        ]
        config = CandidateConfig("id", "h", "t", "e", "a", "s", "a", "b", ("f",), (1,))
        self.assertTrue(acceptance_gates({}, rows, config, 5)["p95Valid"])
        rows[1]["wallClockSeconds"] = 10.5
        self.assertFalse(acceptance_gates({}, rows, config, 5)["p95Valid"])

    def test_escalation_is_decided_per_fixture_seed_and_ci(self) -> None:
        rows = []
        for fixture, candidate in (("stable", [8.0, 8.1, 8.2]), ("uncertain", [8.0, 10.0, 12.0])):
            rows.extend({"fixture": fixture, "seed": 3, "variant": "baseline",
                         "wallClockSeconds": value, "success": True}
                        for value in [10.0, 10.0, 10.0])
            rows.extend({"fixture": fixture, "seed": 3, "variant": "candidate",
                         "wallClockSeconds": value, "success": True} for value in candidate)
        cases = cases_needing_escalation(rows, 5, 1)
        self.assertEqual([case["fixture"] for case in cases], ["uncertain"])
        self.assertTrue(cases[0]["crossesNoImprovement"])

    def test_drift_and_performance_are_gated_per_fixture_seed(self) -> None:
        rows = []
        for fixture, baseline, candidate in (("good", (1.0, 1.01), (0.9, 0.91)),
                                              ("bad", (1.0, 1.06), (0.8, 1.2))):
            for variant, timings in (("baseline", baseline), ("candidate", candidate)):
                rows.extend({"fixture": fixture, "seed": 7, "variant": variant,
                             "wallClockSeconds": timing, "success": True,
                             "outputs": []} for timing in timings)
        self.assertFalse(drift_by_case(rows, 5)["valid"])
        config = CandidateConfig("id", "h", "t", "e", "a", "s", "a", "b", ("f",), (1,))
        gates = acceptance_gates({}, rows, config, 5)
        self.assertFalse(gates["p95Valid"])
        self.assertEqual(len(gates["performanceCases"]), 2)

    def test_output_path_enforces_candidate_and_run_identity(self) -> None:
        with TemporaryDirectory() as directory:
            repository = Path(directory)
            valid = repository / "artifacts" / "optimization" / "c01" / "run-1"
            validate_output_path(repository, valid, "c01")
            with self.assertRaises(ValueError):
                validate_output_path(repository, repository / "elsewhere", "c01")

    def test_worktree_validation_rejects_dirty_or_different_fixtures(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, candidate = root / "baseline", root / "candidate"
            commits = {"baseline": self.make_git_fixture(baseline, '{"text":"same"}'),
                       "candidate": self.make_git_fixture(candidate, '{"text":"same"}')}
            worktrees = {"baseline": baseline, "candidate": candidate}
            metadata = validate_worktrees(worktrees, commits, ("fixture.json",))
            self.assertEqual(metadata["fixture.json"]["bytes"], b'{"text":"same"}')
            (candidate / "dirty.txt").write_text("dirty")
            with self.assertRaisesRegex(ValueError, "must be clean"):
                validate_worktrees(worktrees, commits, ("fixture.json",))

            (candidate / "dirty.txt").unlink()
            (candidate / "fixture.json").write_text('{"text":"different"}')
            subprocess.run(["git", "-C", str(candidate), "add", "fixture.json"], check=True)
            subprocess.run(["git", "-C", str(candidate), "-c", "user.name=Test", "-c",
                            "user.email=test@example.invalid", "commit", "-qm", "different"], check=True)
            commits["candidate"] = subprocess.run(
                ["git", "-C", str(candidate), "rev-parse", "HEAD"], check=True,
                capture_output=True, text=True).stdout.strip()
            with self.assertRaisesRegex(ValueError, "fixture differs"):
                validate_worktrees(worktrees, commits, ("fixture.json",))

    def test_environment_changes_invalidate_and_incomplete_runs_are_detected(self) -> None:
        before = {"capturedAt": "before", "python": "3.13", "modelHashes": {"model": "a"}}
        self.assertTrue(environment_matches(before, {**before, "capturedAt": "after"}))
        self.assertFalse(environment_matches(before, {**before, "modelHashes": {"model": "b"}}))
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(evidence_run_complete(root))
            (root / "complete.json").write_text("{}")
            self.assertFalse(evidence_run_complete(root))
            (root / "complete.json").write_text(json.dumps({
                "candidateId": root.parent.name, "runId": root.name,
            }))
            write_sha256_manifest(root)
            self.assertTrue(evidence_run_complete(root))


if __name__ == "__main__":
    unittest.main()

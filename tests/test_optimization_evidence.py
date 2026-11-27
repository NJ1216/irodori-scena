from __future__ import annotations

import scena_test_isolation  # noqa: F401
import hashlib
import json
import subprocess
import sys
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.optimization_evidence import (
    CandidateConfig,
    abba_order,
    drift_assessment,
    result_evidence,
    sha256_manifest,
    write_sha256_manifest,
)


def valid_config() -> dict[str, object]:
    return {
        "candidate_id": "c04-context-cache",
        "hypothesis": "Cache reuse reduces wall-clock time without changing PCM.",
        "target_conditions": "v4.1 Small, MPS, fixed input and seed",
        "excluded_conditions": "Reference cloning until separately tested",
        "acceptance_thresholds": "median >=5%; p95 not worse; PCM identical",
        "stop_conditions": "process crash, mismatch, or unsafe memory pressure",
        "baseline_commit": "a" * 40,
        "candidate_commit": "b" * 40,
        "fixtures": ["tests/inference/example.json"],
        "seeds": [42],
    }


class OptimizationEvidenceTests(unittest.TestCase):
    def test_config_defaults_and_validation(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_text(json.dumps(valid_config()), encoding="utf-8")
            loaded = CandidateConfig.load(path)
            self.assertEqual(loaded.repetitions, 10)
            self.assertEqual(loaded.max_repetitions, 30)
            rejected_seed = valid_config()
            rejected_seed["seeds"] = [True]
            path.write_text(json.dumps(rejected_seed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "seeds"):
                CandidateConfig.load(path)
            too_many = valid_config()
            too_many["max_repetitions"] = 31
            path.write_text(json.dumps(too_many), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "max_repetitions"):
                CandidateConfig.load(path)
            invalid_memory = valid_config()
            invalid_memory["requires_mps_memory"] = "yes"
            path.write_text(json.dumps(invalid_memory), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires_mps_memory"):
                CandidateConfig.load(path)
            missing_ceiling = valid_config()
            missing_ceiling["requires_mps_memory"] = True
            path.write_text(json.dumps(missing_ceiling), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "memory_ceiling_bytes"):
                CandidateConfig.load(path)
            broken = valid_config()
            broken["hypothesis"] = ""
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hypothesis"):
                CandidateConfig.load(path)

    def test_abba_order_is_balanced_and_deterministic(self) -> None:
        self.assertEqual(
            abba_order(10),
            ["baseline", "candidate", "candidate", "baseline"] * 2 + ["baseline", "candidate"],
        )
        with self.assertRaises(ValueError):
            abba_order(0)
        escalated = abba_order(60)
        self.assertEqual((escalated.count("baseline"), escalated.count("candidate")), (30, 30))

    def test_five_percent_drift_is_invalid(self) -> None:
        self.assertTrue(drift_assessment(10.0, 10.499)["valid"])
        assessment = drift_assessment(10.0, 10.5)
        self.assertFalse(assessment["valid"])
        self.assertEqual(assessment["reason"], "baseline-drift-at-or-above-limit")

    def test_result_and_pcm_hashes_and_directory_manifest(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            result = root / "result.json"
            result.write_bytes(b'{"ok":true}\n')
            wav = root / "sample.wav"
            with wave.open(str(wav), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(8_000)
                output.writeframes(b"\x01\x00" * 4_000)
            self.assertEqual(result_evidence(result)["sha256"], hashlib.sha256(result.read_bytes()).hexdigest())
            wav_evidence = result_evidence(wav)
            self.assertEqual(wav_evidence["pcm"]["duration_seconds"], 0.5)
            self.assertEqual(wav_evidence["pcm"]["sample_width_bytes"], 2)
            self.assertEqual(wav_evidence["pcm"]["compression_type"], "NONE")
            self.assertEqual(wav_evidence["pcmSha256"], hashlib.sha256(b"\x01\x00" * 4_000).hexdigest())
            destination = write_sha256_manifest(root)
            manifest = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(manifest, sha256_manifest(root))
            self.assertNotIn(destination.name, manifest)

    def test_cli_dry_run_does_not_create_output(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "candidate.json"
            config.write_text(json.dumps(valid_config()), encoding="utf-8")
            destination = root / "evidence"
            result = subprocess.run(
                [sys.executable, "-m", "tools.optimization_evidence", "--config", str(config),
                 "--output", str(destination), "--dry-run"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(destination.exists())
            self.assertEqual(len(json.loads(result.stdout)["order"]), 20)


if __name__ == "__main__":
    unittest.main()

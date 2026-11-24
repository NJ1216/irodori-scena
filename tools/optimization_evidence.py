"""Reproducible, secret-free evidence helpers for optimization candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import wave
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence

from tools.baseline_utils import git_revision, sha256, wav_details


REQUIRED_TEXT_FIELDS = (
    "candidate_id",
    "hypothesis",
    "target_conditions",
    "excluded_conditions",
    "acceptance_thresholds",
    "stop_conditions",
    "baseline_commit",
    "candidate_commit",
)


@dataclass(frozen=True)
class CandidateConfig:
    candidate_id: str
    hypothesis: str
    target_conditions: str
    excluded_conditions: str
    acceptance_thresholds: str
    stop_conditions: str
    baseline_commit: str
    candidate_commit: str
    fixtures: tuple[str, ...]
    seeds: tuple[int, ...]
    repetitions: int = 10
    max_repetitions: int = 30
    drift_limit_percent: float = 5.0
    requires_mps_memory: bool = False
    memory_ceiling_bytes: int | None = None

    @classmethod
    def load(cls, path: Path) -> "CandidateConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("candidate config must be a JSON object")
        missing = [field for field in REQUIRED_TEXT_FIELDS if not str(raw.get(field, "")).strip()]
        if missing:
            raise ValueError(f"candidate config has empty required fields: {', '.join(missing)}")
        fixtures = raw.get("fixtures")
        seeds = raw.get("seeds")
        if not isinstance(fixtures, list) or not fixtures or not all(isinstance(item, str) and item for item in fixtures):
            raise ValueError("fixtures must be a non-empty string array")
        if not isinstance(seeds, list) or not seeds or not all(type(item) is int for item in seeds):
            raise ValueError("seeds must be a non-empty integer array")
        repetitions = int(raw.get("repetitions", 10))
        max_repetitions = int(raw.get("max_repetitions", 30))
        drift_limit = float(raw.get("drift_limit_percent", 5.0))
        requires_mps_memory = raw.get("requires_mps_memory", False)
        memory_ceiling = raw.get("memory_ceiling_bytes")
        if repetitions < 1 or max_repetitions < repetitions or max_repetitions > 30:
            raise ValueError("repetitions must be positive and no greater than max_repetitions")
        if drift_limit <= 0:
            raise ValueError("drift_limit_percent must be positive")
        if type(requires_mps_memory) is not bool:
            raise ValueError("requires_mps_memory must be a boolean")
        if memory_ceiling is not None and (type(memory_ceiling) is not int or memory_ceiling <= 0):
            raise ValueError("memory_ceiling_bytes must be a positive integer")
        if requires_mps_memory and memory_ceiling is None:
            raise ValueError("MPS candidates require memory_ceiling_bytes")
        return cls(
            **{field: str(raw[field]).strip() for field in REQUIRED_TEXT_FIELDS},
            fixtures=tuple(fixtures),
            seeds=tuple(seeds),
            repetitions=repetitions,
            max_repetitions=max_repetitions,
            drift_limit_percent=drift_limit,
            requires_mps_memory=requires_mps_memory,
            memory_ceiling_bytes=memory_ceiling,
        )


def abba_order(repetitions: int) -> list[str]:
    """Return balanced alternating measurements, trimming the final block if needed."""
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    return (["baseline", "candidate", "candidate", "baseline"] * ((repetitions + 3) // 4))[:repetitions]


def baseline_drift_percent(before: float, after: float) -> float:
    if before <= 0 or after < 0:
        raise ValueError("baseline timings must have a positive start and non-negative end")
    return abs(after - before) / before * 100.0


def drift_assessment(before: float, after: float, limit_percent: float = 5.0) -> dict[str, Any]:
    drift = baseline_drift_percent(before, after)
    return {
        "before": before,
        "after": after,
        "driftPercent": round(drift, 6),
        "limitPercent": limit_percent,
        "valid": drift < limit_percent,
        "reason": None if drift < limit_percent else "baseline-drift-at-or-above-limit",
    }


def result_evidence(path: Path, root: Path | None = None) -> dict[str, Any]:
    evidence_path = path.relative_to(root).as_posix() if root else path.name
    evidence: dict[str, Any] = {"path": evidence_path, "bytes": path.stat().st_size, "sha256": sha256(path)}
    if path.suffix.lower() == ".wav":
        evidence["pcm"] = wav_details(path)
        digest = hashlib.sha256()
        with wave.open(str(path), "rb") as source:
            for block in iter(lambda: source.readframes(1024 * 1024), b""):
                digest.update(block)
        evidence["pcmSha256"] = digest.hexdigest()
    return evidence


def sha256_manifest(root: Path, *, excluded_names: set[str] | None = None) -> dict[str, str]:
    exclusions = excluded_names or {"sha256-manifest.json"}
    return {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in exclusions
    }


def write_sha256_manifest(root: Path) -> Path:
    destination = root / "sha256-manifest.json"
    destination.write_text(
        json.dumps(sha256_manifest(root), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _command_text(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def git_status(path: Path | None) -> str | None:
    return _command_text(["git", "-C", str(path), "status", "--short"]) if path else None


def environment_manifest(
    repository: Path,
    engine: Path | None = None,
    *,
    provider: str | None = None,
    model_files: Sequence[Path] = (),
) -> dict[str, Any]:
    torch_version = _command_text([sys.executable, "-c", "import torch; print(torch.__version__)"])
    return {
        "capturedAt": datetime.now(UTC).isoformat(),
        "repositoryCommit": git_revision(repository),
        "engineCommit": git_revision(engine) if engine else None,
        "engineStatus": git_status(engine),
        "platform": platform.platform(),
        "macOSVersion": platform.mac_ver()[0] or None,
        "python": sys.version.split()[0],
        "pythonImplementation": platform.python_implementation(),
        "pytorch": torch_version,
        "provider": provider,
        "power": _command_text(["pmset", "-g", "batt"]),
        "thermal": _command_text(["pmset", "-g", "therm"]),
        "modelHashes": {str(path): sha256(path) for path in model_files},
    }


def execution_plan(config: CandidateConfig) -> dict[str, Any]:
    return {
        "candidate": asdict(config),
        "order": [
            {"ordinal": index + 1, "fixture": fixture, "seed": seed, "variant": variant}
            for index, (fixture, seed, variant) in enumerate(
                (fixture, seed, variant) for fixture in config.fixtures for seed in config.seeds
                for variant in abba_order(config.repetitions * 2)
            )
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare a reproducible optimization evidence run")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = CandidateConfig.load(args.config)
    plan = execution_plan(config)
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "candidate.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "environment.json").write_text(
        json.dumps(environment_manifest(args.repository, args.engine), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_sha256_manifest(args.output)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

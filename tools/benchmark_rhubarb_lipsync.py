#!/usr/bin/env python3
"""Evaluate Rhubarb on 30 deterministic selected takes without changing SCENA."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from rhubarb_lipsync_benchmark import (
    CATEGORY_QUOTAS,
    cues_to_lab,
    lab_text,
    load_selected_takes,
    markdown_scorecard,
    parse_mouth_cues,
    percentile,
    preview_html,
    select_corpus,
    sha256,
    wav_duration,
)


REPOSITORY = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Rhubarb phonetic mouth shapes for PSDToolKit-compatible LAB.")
    parser.add_argument("--rhubarb", required=True, type=Path, help="External Rhubarb executable (not downloaded).")
    parser.add_argument("--project", required=True, type=Path, help="Existing .scena project directory.")
    parser.add_argument("--output", required=True, type=Path, help="New or empty result directory; use artifacts/ or outside Git.")
    return parser.parse_args()


def ensure_safe_output(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output directory must be new or empty: {output}")
    try:
        relative = output.resolve().relative_to(REPOSITORY)
    except ValueError:
        return
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(relative)], cwd=REPOSITORY, check=False
    ).returncode == 0
    if not ignored:
        raise ValueError("Output inside the repository must be ignored by Git (use artifacts/...).")


def rhubarb_version(executable: Path) -> str:
    completed = subprocess.run([str(executable), "--version"], capture_output=True, text=True, check=False)
    value = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0 or not value:
        raise ValueError("Could not read Rhubarb version with --version.")
    return value


def run_once(executable: Path, wav: Path, raw_path: Path) -> tuple[dict[str, Any], float]:
    command = [
        str(executable), "-f", "json", "-r", "phonetic", "--extendedShapes", "X",
        "--machineReadable", "-o", str(raw_path), str(wav),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        message = completed.stderr.strip().splitlines()[-1:] or ["no diagnostic"]
        raise RuntimeError(f"Rhubarb exited {completed.returncode}: {message[0]}")
    return json.loads(raw_path.read_text(encoding="utf-8")), elapsed


def main() -> int:
    args = parse_args()
    executable, project, output = args.rhubarb.resolve(), args.project.resolve(), args.output.resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise SystemExit(f"Rhubarb is not an executable file: {executable}")
    try:
        ensure_safe_output(output)
        samples = select_corpus(load_selected_takes(project))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise SystemExit(str(error)) from error
    output.mkdir(parents=True, exist_ok=True)
    records, warm_rtfs = [], []
    all_deterministic = True
    successful = 0
    for index, sample in enumerate(samples, 1):
        prefix = f"{index:02d}_{sample.category}_{sample.key}"
        duration = wav_duration(sample.wav)
        payloads, timings = [], []
        try:
            for run in range(3):
                raw_path = output / (f"{prefix}.raw.json" if run == 0 else f".{prefix}.repeat-{run + 1}.json")
                payload, elapsed = run_once(executable, sample.wav, raw_path)
                payloads.append(payload)
                timings.append(elapsed)
                if run:
                    raw_path.unlink()
            cue_sets = [parse_mouth_cues(payload) for payload in payloads]
            deterministic = cue_sets[1:] == cue_sets[:1] * 2
            all_deterministic &= deterministic
            lab = cues_to_lab(cue_sets[0], duration)
            (output / f"{prefix}.lab").write_text(lab_text(lab), encoding="utf-8")
            warm_rtfs.extend(elapsed / duration for elapsed in timings[1:])
            successful += 1
            records.append({
                "key": sample.key, "category": sample.category, "lineId": sample.line_id, "takeId": sample.take_id,
                "text": sample.text, "wavSha256": sha256(sample.wav), "wavDurationSeconds": duration,
                "elapsedSeconds": timings, "warmRtf": [value / duration for value in timings[1:]],
                "deterministic": deterministic, "lab": lab, "status": "success",
            })
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            records.append({
                "key": sample.key, "category": sample.category, "lineId": sample.line_id, "takeId": sample.take_id,
                "text": sample.text, "wavSha256": sha256(sample.wav), "wavDurationSeconds": duration,
                "status": "error", "error": str(error),
            })
    warm_p95 = percentile(warm_rtfs, 0.95)
    # Repeated Rhubarb inference is observed rather than gated: SCENA caches
    # the first successful result by release and WAV hash for stable exports.
    automatic_pass = successful == 30 and warm_p95 is not None and warm_p95 <= 0.60
    summary = {
        "schemaVersion": 1,
        "description": "PSDToolKit-compatible approximate mouth-shape LAB; not phoneme or training labels.",
        "rhubarb": {"version": rhubarb_version(executable), "sha256": sha256(executable)},
        "host": {"os": platform.platform(), "cpu": platform.processor() or platform.machine()},
        "selection": {"count": len(samples), "quotas": CATEGORY_QUOTAS},
        "successfulCount": successful, "deterministic": all_deterministic,
        "warmP95Rtf": warm_p95, "automaticPass": automatic_pass, "records": records,
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "scorecard.md").write_text(markdown_scorecard(summary), encoding="utf-8")
    successful_records = [record for record in records if record["status"] == "success"]
    successful_samples = [sample for sample in samples if any(record["key"] == sample.key for record in successful_records)]
    (output / "preview.html").write_text(preview_html(successful_samples, successful_records), encoding="utf-8")
    windows = output / "windows-psdtoolkit"
    windows.mkdir()
    representative = []
    per_category: dict[str, int] = {}
    for sample in successful_samples:
        limit = 2 if sample.category in {"ordinary", "sibilants", "closed_mouth", "laughter_repetition"} else 1
        if per_category.get(sample.category, 0) >= limit:
            continue
        source_lab = next(output.glob(f"*_{sample.category}_{sample.key}.lab"))
        stem = f"{len(representative) + 1:02d}_{sample.category}_{sample.key}"
        shutil.copyfile(sample.wav, windows / f"{stem}.wav")
        shutil.copyfile(source_lab, windows / f"{stem}.lab")
        representative.append(stem)
        per_category[sample.category] = per_category.get(sample.category, 0) + 1
        if len(representative) == 10:
            break
    summary["windowsPsdtoolkitRepresentative"] = representative
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "automaticPass": automatic_pass, "successfulCount": successful}, ensure_ascii=False))
    return 0 if automatic_pass else 1


if __name__ == "__main__":
    sys.exit(main())

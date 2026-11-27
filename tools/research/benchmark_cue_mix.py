"""Alternating Python/Rust simultaneous-cue benchmark with isolated RSS samples."""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np
import psutil


REPOSITORY = Path(__file__).resolve().parents[2]


def make_fixture(root: Path, count: int = 8, seconds: int = 30) -> list[tuple[Path, float]]:
    rate = 48_000
    positions = np.arange(rate * seconds, dtype=np.float32)
    members = []
    for index in range(count):
        path = root / f"member-{index}.wav"
        left = np.sin(positions * (0.011 + index * 0.0013) + index * 0.2) * 0.24
        right = np.sin(positions * (0.013 + index * 0.0011) + index * 0.3) * 0.24
        samples = np.column_stack((left, right))
        with wave.open(str(path), "wb") as writer:
            writer.setparams((2, 2, rate, 0, "NONE", "not compressed"))
            writer.writeframes(np.round(samples * 32768).astype("<i2").tobytes())
        members.append((path, index * 0.017))
    return members


def worker(implementation: str, manifest: Path, output: Path) -> dict[str, float]:
    from server.native_processing import mix_pcm_members_wav
    from tests.audio_cue_reference import mix_pcm_members

    members = [(Path(path), float(offset)) for path, offset in json.loads(manifest.read_text())]
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = baseline
    finished = threading.Event()

    def sample() -> None:
        nonlocal peak
        while not finished.wait(0.001):
            peak = max(peak, process.memory_info().rss)

    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    started = time.perf_counter()
    (mix_pcm_members if implementation == "python" else mix_pcm_members_wav)(members, output)
    duration = time.perf_counter() - started
    peak = max(peak, process.memory_info().rss)
    finished.set()
    sampler.join()
    return {
        "seconds": duration,
        "peakRssDeltaBytes": float(max(0, peak - baseline)),
        "outputBytes": float(output.stat().st_size),
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * fraction) - 1)]


def run(rounds: int) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        members = make_fixture(root)
        manifest = root / "members.json"
        manifest.write_text(json.dumps([(str(path), offset) for path, offset in members]))
        results: dict[str, list[dict[str, float]]] = {"python": [], "rust": []}
        for iteration in range(rounds):
            order = ("python", "rust") if iteration % 2 == 0 else ("rust", "python")
            for implementation in order:
                output = root / f"{implementation}-{iteration}.wav"
                command = [
                    str(REPOSITORY / ".venv/bin/python"), __file__, "--worker", implementation,
                    str(manifest), str(output),
                ]
                completed = subprocess.run(command, cwd=REPOSITORY, check=True, capture_output=True, text=True)
                results[implementation].append(json.loads(completed.stdout))
        summary: dict[str, object] = {"rounds": rounds, "implementations": {}}
        for name, samples in results.items():
            durations = [sample["seconds"] for sample in samples]
            rss = [sample["peakRssDeltaBytes"] for sample in samples]
            summary["implementations"][name] = {
                "medianSeconds": statistics.median(durations),
                "p95Seconds": percentile(durations, 0.95),
                "medianPeakRssDeltaBytes": statistics.median(rss),
                "outputBytes": samples[0]["outputBytes"],
            }
        python = summary["implementations"]["python"]
        rust = summary["implementations"]["rust"]
        summary["comparison"] = {
            "medianTimeImprovementPercent": (python["medianSeconds"] - rust["medianSeconds"]) / python["medianSeconds"] * 100,
            "p95TimeChangePercent": (rust["p95Seconds"] - python["p95Seconds"]) / python["p95Seconds"] * 100,
            "medianPeakRssReductionPercent": (python["medianPeakRssDeltaBytes"] - rust["medianPeakRssDeltaBytes"]) / max(python["medianPeakRssDeltaBytes"], 1) * 100,
            "outputSizeChangePercent": (rust["outputBytes"] - python["outputBytes"]) / python["outputBytes"] * 100,
        }
        return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, choices=(10, 30), default=10)
    parser.add_argument("--worker", choices=("python", "rust"))
    parser.add_argument("paths", nargs="*")
    arguments = parser.parse_args()
    if arguments.worker:
        print(json.dumps(worker(arguments.worker, *(Path(value) for value in arguments.paths))))
    else:
        print(json.dumps(run(arguments.rounds), indent=2))

"""Compare SCENA's verified MPS/CUDA path with upstream eager for one fixed case."""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


class MpsPeakTracker:
    def __init__(self, torch: object, destination: Path, interval: float = 0.005) -> None:
        self.torch = torch
        self.destination = destination
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _current(self) -> int:
        try:
            return max(0, int(self.torch.mps.driver_allocated_memory()))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return 0

    def _sample(self) -> None:
        while not self._stop.wait(self.interval):
            self.peak = max(self.peak, self._current())

    def start(self) -> None:
        self.peak = self._current()
        self._thread.start()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self.peak = max(self.peak, self._current())
        self._stop.set()
        self._thread.join(timeout=1)
        current = self._current()
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination.write_text(json.dumps({"currentBytes": current, "peakBytes": max(current, self.peak)}))


def arguments() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    commit = "8224dafb46d0aba89209a8f905f1cb7e3299d9c1"
    revision = "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
    codec_revision = "47376ee24834d7a05a48ebabfe3cde29b3c5e214"
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, default=root / "scena-data/tts/engines" / commit)
    parser.add_argument("--checkpoint", type=Path, default=root / "scena-data/tts/models" / revision / "model.safetensors")
    parser.add_argument("--codec", type=Path, default=root / "scena-data/tts/codecs" / codec_revision / "weights.pth")
    parser.add_argument("--steps", type=int, default=16)
    parser.add_argument("--device", choices=("mps", "cuda"), default="mps")
    parser.add_argument("--schedule", choices=("linear", "sway"), default="sway")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--warmup-pairs", type=int, default=1)
    parser.add_argument(
        "--seconds",
        type=float,
        help="Use a fixed duration for checkpoints without duration prediction.",
    )
    parser.add_argument("--engine-commit", default=commit)
    parser.add_argument(
        "--model-identity",
        default=f"Aratako/Irodori-TTS-v4.1-Small@{revision}",
    )
    parser.add_argument(
        "--exercise-candidate-profile",
        action="store_true",
        help="Temporarily exercise an unlisted model identity in this validator process only.",
    )
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--tokenizer", type=Path)
    return parser.parse_args()


def checkpoint_with_tokenizer(checkpoint: Path, tokenizer: Path | None) -> Path:
    if tokenizer is None or tokenizer.resolve() == (checkpoint.parent / "tokenizer").resolve():
        return checkpoint.resolve()
    identity = hashlib.sha256(f"{checkpoint.resolve()}\0{tokenizer.resolve()}".encode()).hexdigest()[:20]
    root = Path(tempfile.gettempdir()) / "irodori-scena-validation" / identity
    root.mkdir(parents=True, exist_ok=True)
    for link, target in ((root / "model.safetensors", checkpoint), (root / "tokenizer", tokenizer)):
        if not (link.is_symlink() and link.resolve() == target.resolve()):
            link.unlink(missing_ok=True)
            link.symlink_to(target.resolve(), target_is_directory=target.is_dir())
    return root / "model.safetensors"


def promote_candidate(adapter, runtime, args, *, has_reference: bool) -> None:
    if not args.exercise_candidate_profile:
        return
    adapter.VERIFIED_MODELS.add(args.model_identity)
    if args.device != "cuda":
        return
    cuda_identity = adapter._cuda_runtime_identity(runtime)
    if cuda_identity is None:
        raise RuntimeError("CUDA runtime identity is unavailable")
    route = (args.model_identity, *cuda_identity, args.schedule, args.steps, has_reference)
    adapter.VERIFIED_CUDA_ROUTES.add(route)


def main() -> int:
    args = arguments()
    import torch

    memory_path = os.environ.get("SCENA_OPTIMIZATION_MEMORY_PATH")
    if memory_path:
        tracker = MpsPeakTracker(torch, Path(memory_path))
        tracker.start()
        atexit.register(tracker.stop)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(args.engine.resolve()))
    from irodori_tts.inference_runtime import RuntimeKey, SamplingRequest, get_cached_runtime, save_wav
    from server import irodori_acceleration_adapter

    runtime_checkpoint = checkpoint_with_tokenizer(args.checkpoint, args.tokenizer)
    runtime, _ = get_cached_runtime(RuntimeKey(
        checkpoint=str(runtime_checkpoint), model_device=args.device,
        codec_repo=str(args.codec.resolve()), model_precision="fp32",
        codec_device=args.device, codec_precision="fp32",
        codec_deterministic_encode=True, codec_deterministic_decode=True,
        compile_model=False, compile_dynamic=False,
    ))
    fixture_path = os.environ.get("SCENA_OPTIMIZATION_FIXTURE")
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8-sig")) if fixture_path else {}
    if not isinstance(fixture, dict):
        raise ValueError("optimization fixture must be a JSON object")
    dialogue = fixture.get("dialogue")
    fixture_text = fixture.get("text")
    if fixture_text is None and isinstance(dialogue, list) and dialogue and isinstance(dialogue[0], dict):
        fixture_text = dialogue[0].get("text")
    if fixture_path and not isinstance(fixture_text, str):
        raise ValueError("optimization fixture must provide text or dialogue[0].text")
    fixture_caption = fixture.get("caption", fixture.get("scene_context", "落ち着いて自然に話す。"))
    reference = Path(str(fixture["reference"])) if fixture.get("reference") else args.reference
    promote_candidate(irodori_acceleration_adapter, runtime, args, has_reference=reference is not None)
    seed = int(os.environ.get("SCENA_OPTIMIZATION_SEED", fixture.get("seed", 19451217)))
    request = SamplingRequest(
        text=str(fixture_text or "検証用の短い音声です。"),
        caption=str(fixture_caption),
        ref_wav=str(reference.resolve()) if reference else None,
        no_ref=reference is None, num_candidates=1, decode_mode="sequential",
        seconds=fixture.get("seconds", args.seconds), duration_scale=1.0,
        num_steps=int(fixture.get("steps", args.steps)),
        cfg_scale_text=3.0, cfg_scale_caption=3.0, cfg_scale_speaker=5.0,
        cfg_guidance_mode="independent", cfg_min_t=0.5, cfg_max_t=1.0,
        context_kv_cache=True, speaker_uncond_mode="mask", seed=seed,
        t_schedule_mode=args.schedule, sway_coeff=-1.0, trim_tail=True,
        tail_window_size=20, tail_std_threshold=0.05, tail_mean_threshold=0.1,
    )
    def eager_call():
        started = time.perf_counter()
        result = runtime.synthesize(request, log_fn=None)
        return result, time.perf_counter() - started

    def optimized_call():
        started = time.perf_counter()
        result, execution = irodori_acceleration_adapter.run(
            runtime, request, engine_commit=args.engine_commit, model_identity=args.model_identity,
        )
        return result, execution, time.perf_counter() - started

    run_dir_value = os.environ.get("SCENA_OPTIMIZATION_RUN_DIR")
    if run_dir_value:
        variant = os.environ.get("SCENA_OPTIMIZATION_VARIANT", "candidate")
        for _ in range(max(0, args.warmup_pairs)):
            eager_call() if variant == "baseline" else optimized_call()
        if variant == "baseline":
            selected, seconds = eager_call()
            execution = {"mode": "eager"}
        else:
            selected, execution, seconds = optimized_call()
        run_dir = Path(run_dir_value)
        save_wav(run_dir / "audio.wav", selected.audio, selected.sample_rate)
        executed_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
        ).stdout.strip()
        canonical = {
            "sampleRate": int(selected.sample_rate),
            "sampleCount": int(selected.audio.numel()),
            "pcmSha256": hashlib.sha256(selected.audio.detach().cpu().numpy().tobytes()).hexdigest(),
        }
        (run_dir / "result.json").write_text(json.dumps({
            "canonicalResult": canonical, "executedCommit": executed_commit,
            "fixture": fixture_path, "seed": seed, "variant": variant,
            "metrics": {"seconds": seconds}, "provenance": {"execution": execution},
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 0

    def compare_pair(*, optimized_first: bool) -> tuple[dict[str, object], object, object]:

        if optimized_first:
            optimized, execution, optimized_seconds = optimized_call()
            eager, eager_seconds = eager_call()
        else:
            eager, eager_seconds = eager_call()
            optimized, execution, optimized_seconds = optimized_call()
        return ({
            "equal": bool(torch.equal(eager.audio, optimized.audio)),
            "maxAbsDifference": float((eager.audio - optimized.audio).abs().max().item()),
            "eagerSeconds": round(eager_seconds, 4),
            "optimizedSeconds": round(optimized_seconds, 4),
            "order": "optimized-first" if optimized_first else "eager-first",
            "execution": execution,
        }, eager, optimized)

    warmup_results = [compare_pair(optimized_first=bool(index % 2))
                      for index in range(max(0, args.warmup_pairs))]
    measured = [compare_pair(optimized_first=not bool(index % 2)) for index in range(max(1, args.runs))]
    warmups = [item[0] for item in warmup_results]
    rows = [item[0] for item in measured]
    def summary(key: str) -> dict[str, float]:
        values = sorted(float(row[key]) for row in rows)
        return {
            "median": round(statistics.median(values), 4),
            "p95": round(values[max(0, math.ceil(len(values) * 0.95) - 1)], 4),
        }

    payload = {
        "conditions": {
            "steps": args.steps,
            "schedule": args.schedule,
            "runs": len(rows),
            "warmupPairs": len(warmups),
            "seed": seed,
            "reference": bool(reference),
            "seconds": fixture.get("seconds", args.seconds),
        },
        "eager": summary("eagerSeconds"),
        "optimized": summary("optimizedSeconds"),
        "rows": rows,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    valid = all(
        row["equal"] and row["execution"]["optimizationProfile"] == (
            irodori_acceleration_adapter.MPS_PROFILE if args.device == "mps"
            else irodori_acceleration_adapter.CUDA_PROFILE
        )
        for row in warmups + rows
    )
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

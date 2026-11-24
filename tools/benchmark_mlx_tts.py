"""Benchmark SCENA's MLX TTS path inside the pinned mlx-audio environment.

Run with the MLX environment's Python, for example:
  scena-data/tts/environments/mlx-audio-0.5.0/bin/python tools/benchmark_mlx_tts.py \
    --model-path scena-data/tts/models/<revision> --variant-id mlx-fp16 --features none --out result.json

`--features none` compares the plain path with itself (A/A noise floor);
`--features adapter` runs the candidate through server.mlx_acceleration_adapter
with no feature enabled; any other comma-separated list enables those features.
Baseline and candidate alternate inside one process so background load from
other programs affects both sides alike.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.mlx_benchmark_stats import pcm_sha256, snr_db, summarize  # noqa: E402
from tools.mlx_stage_profile import profile_once  # noqa: E402

CORPUS = {
    "short": ("おはよう、今日もよろしくね。", "明るく元気な若い女性の声で、はきはきと話す。"),
    "medium": ("昨日の雨が嘘みたいに晴れたから、少し遠回りして駅まで歩いてみようと思うんだ。", "落ち着いた男性の声で、穏やかに語りかけるように話す。"),
    "long": ("この街に引っ越してきてから、もう三年が経ちました。最初は道もわからず、毎日のように迷っていましたが、今では近所のパン屋さんの焼き上がり時間まで覚えています。", "柔らかい女性の声で、懐かしむようにゆっくり話す。"),
}
PRESETS = {"sway16": ("sway", 16), "linear40": ("linear", 40)}
SEED = 19451217


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--variant-id", default="mlx-fp16")
    parser.add_argument("--runtime-version", default="mlx-audio@0.5.0")
    parser.add_argument("--features", default="none")
    parser.add_argument("--baseline-features", default="none", help="features for the baseline side (default: plain path)")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--warmup-pairs", type=int, default=1)
    parser.add_argument("--texts", default="short,medium,long")
    parser.add_argument("--presets", default="sway16,linear40")
    parser.add_argument("--reference-wav", default="", help="path, 'auto' (generate one), or empty for no-reference only")
    parser.add_argument("--audio-dir", default="")
    parser.add_argument("--vary-seed", action="store_true", help="pair i uses seed+i; compare the PCM of every pair (retake check)")
    parser.add_argument("--save-audio", action="store_true", help="write the first baseline/candidate WAV of each case to --audio-dir")
    parser.add_argument("--reference-only", action="store_true", help="measure only cases with a reference WAV")
    parser.add_argument("--fresh-caches", action="store_true", help="clear adapter caches before every candidate call (first-take timing)")
    parser.add_argument("--profile-runs", type=int, default=0, help="extra eval-forced runs per case for a stage breakdown")
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def load_model(model_path: str, variant_id: str) -> Any:
    os.environ["IRODORI_TTS_MODEL_PATH"] = str(Path(model_path).resolve())
    os.environ["IRODORI_TTS_VARIANT_ID"] = variant_id
    from server import mlx_irodori_worker

    return mlx_irodori_worker._load_model()


def generation_kwargs(text: str, caption: str, preset: str, reference: str | None, seed: int) -> dict[str, Any]:
    schedule, steps = PRESETS[preset]
    return {"text": text, "ref_audio": reference, "instruct": caption, "num_steps": steps,
            "cfg_scale_text": 3.0, "cfg_scale_speaker": 5.0, "cfg_scale_caption": 3.0,
            "t_schedule_mode": schedule, "sway_coeff": -1.0, "duration_scale": 1.0,
            "seconds": None, "rng_seed": seed, "verbose": False}


def plain_call(model: Any) -> Callable[[dict[str, Any]], Any]:
    return lambda kwargs: next(iter(model.generate(**kwargs)))


def adapter_call(model: Any, features: str, runtime_version: str, fresh: bool = False) -> Callable[[dict[str, Any]], Any]:
    """Plain call for "none"; otherwise the adapter with the listed features (aborts on fallback)."""
    if features == "none":
        return plain_call(model)
    from server import mlx_acceleration_adapter as adapter

    # "adapter" alone routes through the adapter with no feature enabled (overhead check).
    enabled = frozenset(item for item in features.split(",") if item and item != "adapter")

    def checked(kwargs: dict[str, Any]) -> Any:
        if fresh:
            adapter.clear_caches()
        result, report = adapter.run(model, kwargs, runtime_version=runtime_version, features=enabled, lora=False)
        # A silent fallback would turn the comparison into baseline vs baseline.
        if report["optimizationProfile"] != adapter.PROFILE:
            raise RuntimeError(f"candidate fell back: {report['fallbackReason']} {report.get('fallbackDetail', '')}")
        return result
    return checked


def samples(result: Any) -> list[float]:
    import numpy as np

    return np.asarray(result.audio, dtype=np.float32).reshape(-1).tolist()


def timed(call: Callable[[dict[str, Any]], Any], kwargs: dict[str, Any]) -> tuple[float, Any]:
    started = time.perf_counter()
    result = call(kwargs)
    return (time.perf_counter() - started) * 1000, result


def other_cpu_percent() -> float:
    try:
        rows = subprocess.run(["ps", "-A", "-o", "pid=,%cpu="], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return -1.0
    total = 0.0
    for row in rows.split("\n"):
        parts = row.split()
        if len(parts) == 2 and int(parts[0]) != os.getpid():
            total += float(parts[1])
    return round(total, 1)


def load_snapshot() -> dict[str, float]:
    return {"loadavg1": round(os.getloadavg()[0], 2), "otherCpuPercent": other_cpu_percent()}


def peak_memory() -> int | None:
    import mlx.core as mx

    reader = getattr(mx, "get_peak_memory", None) or getattr(getattr(mx, "metal", None), "get_peak_memory", None)
    return int(reader()) if reader else None


def reset_peak_memory() -> None:
    import mlx.core as mx

    resetter = getattr(mx, "reset_peak_memory", None) or getattr(getattr(mx, "metal", None), "reset_peak_memory", None)
    if resetter:
        resetter()


def _finite(value: float) -> float | None:
    """JSON has no infinity; identical audio is already reported by pcmIdentical."""
    return round(value, 2) if value not in (float("inf"), float("-inf")) else None


def measure_case(baseline, candidate, kwargs, runs, warmup_pairs, save=None, vary_seed=False) -> dict[str, Any]:
    """Alternate baseline and candidate; with vary_seed, pair i uses seed+i and every pair's PCM is compared."""
    warmup_candidate_ms = []
    for _ in range(warmup_pairs):
        baseline(kwargs)
        warmup_candidate_ms.append(round(timed(candidate, kwargs)[0], 1))
    before = load_snapshot()
    reset_peak_memory()
    base_ms, cand_ms, reference, compared = [], [], None, None
    mismatched: list[int] = []
    for index in range(runs):
        pair_kwargs = {**kwargs, "rng_seed": kwargs["rng_seed"] + index} if vary_seed else kwargs
        order = [(baseline, base_ms), (candidate, cand_ms)] if index % 2 == 0 else [(candidate, cand_ms), (baseline, base_ms)]
        pair: dict[str, str] = {}
        for call, bucket in order:
            elapsed, result = timed(call, pair_kwargs)
            bucket.append(elapsed)
            if vary_seed:
                pair["baseline" if call is baseline else "candidate"] = pcm_sha256(samples(result))
            if call is baseline and reference is None:
                reference = samples(result)
                if save:
                    save("baseline", result)
            if call is candidate and compared is None:
                compared = samples(result)
                if save:
                    save("candidate", result)
        if vary_seed and pair["baseline"] != pair["candidate"]:
            mismatched.append(pair_kwargs["rng_seed"])
    after = load_snapshot()
    equal_length = len(reference) == len(compared)
    return {
        "baselineMs": summarize(base_ms), "candidateMs": summarize(cand_ms), "warmupCandidateMs": warmup_candidate_ms,
        "medianGainPercent": round((1 - summarize(cand_ms)["median"] / summarize(base_ms)["median"]) * 100, 2),
        "pcmIdentical": pcm_sha256(reference) == pcm_sha256(compared) and not mismatched,
        **({"pairsCompared": runs, "mismatchedSeeds": mismatched} if vary_seed else {}),
        "equalLength": equal_length, "snrDb": _finite(snr_db(reference, compared)) if equal_length else None,
        "baselineSha256": pcm_sha256(reference), "peakMemoryBytes": peak_memory(),
        "loadBefore": before, "loadAfter": after,
        "noisy": after["loadavg1"] - before["loadavg1"] > 2.0,
    }


def _saver(audio_dir: Path, stem: str) -> Callable[[str, Any], None]:
    from server.mlx_irodori_worker import _write_wav

    return lambda side, result: _write_wav(audio_dir / f"{stem}-{side}.wav", result.audio, int(result.sample_rate)) and None


def write_reference(model: Any, kwargs: dict[str, Any], audio_dir: Path) -> str:
    from server.mlx_irodori_worker import _write_wav

    result = plain_call(model)(kwargs)
    return _write_wav(audio_dir / "reference.wav", result.audio, int(result.sample_rate))


def main() -> int:
    args = arguments()
    import mlx.core as mx

    audio_dir = Path(args.audio_dir or tempfile.mkdtemp(prefix="scena-mlx-bench-"))
    started = time.perf_counter()
    model = load_model(args.model_path, args.variant_id)
    load_ms = (time.perf_counter() - started) * 1000
    baseline = adapter_call(model, args.baseline_features, args.runtime_version)
    candidate = adapter_call(model, args.features, args.runtime_version, args.fresh_caches)
    texts = [name for name in args.texts.split(",") if name]
    presets = [name for name in args.presets.split(",") if name]
    first_text, first_caption = CORPUS[texts[0]]
    first_kwargs = generation_kwargs(first_text, first_caption, presets[0], None, SEED)
    first_call_ms, _ = timed(baseline, first_kwargs)
    references: list[str | None] = [] if args.reference_only else [None]
    if args.reference_wav == "auto":
        references.append(write_reference(model, first_kwargs, audio_dir))
    elif args.reference_wav:
        references.append(str(Path(args.reference_wav).resolve()))
    cases = []
    for text_name in texts:
        text, caption = CORPUS[text_name]
        for preset in presets:
            for reference in references:
                kwargs = generation_kwargs(text, caption, preset, reference, SEED)
                save = _saver(audio_dir, f"{text_name}-{preset}-{'ref' if reference else 'noref'}") if args.save_audio else None
                row = measure_case(baseline, candidate, kwargs, args.runs, args.warmup_pairs, save, args.vary_seed)
                row.update(text=text_name, preset=preset, reference=reference is not None)
                if args.profile_runs:
                    row["profile"] = [profile_once(model, kwargs) for _ in range(args.profile_runs)]
                cases.append(row)
                print(f"{text_name:6} {preset:8} ref={reference is not None!s:5} base={row['baselineMs']['median']:.1f}ms "
                      f"cand={row['candidateMs']['median']:.1f}ms gain={row['medianGainPercent']:+.2f}% "
                      f"pcm={'same' if row['pcmIdentical'] else 'diff'} noisy={row['noisy']}", flush=True)
    report = {
        "conditions": {"modelPath": str(Path(args.model_path).resolve()), "variantId": args.variant_id,
                        "runtimeVersion": args.runtime_version, "features": args.features, "baselineFeatures": args.baseline_features, "freshCaches": args.fresh_caches, "varySeed": args.vary_seed, "mlx": mx.__version__,
                        "machine": platform.machine(), "python": platform.python_version(), "seed": SEED,
                        "runs": args.runs, "warmupPairs": args.warmup_pairs, "cfg": {"text": 3.0, "caption": 3.0, "speaker": 5.0}},
        "modelLoadMs": round(load_ms, 1), "firstCallMs": round(first_call_ms, 1), "cases": cases,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

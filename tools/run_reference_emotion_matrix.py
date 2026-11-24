#!/usr/bin/env python3
"""Generate one multi-emotion reference voice and its conditioning matrix."""

from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from array import array
from pathlib import Path
from typing import Any

from baseline_utils import git_revision, sha256, wav_details


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT.parent / "_ExternalRepos" / "Irodori-TTS"
FIXTURE = ROOT / "tests" / "inference" / "reference-emotion-matrix-fixture.json"
OUTPUT = ROOT / "artifacts" / "inference" / "reference-emotion-matrix" / "single-pass-segmented"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-dir", type=Path, default=ENGINE)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def read_fixture(path: Path) -> dict[str, Any]:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    required = ("checkpoint", "settings", "primary_performance", "segments", "neutral_probe", "emotion_probes")
    if not all(fixture.get(key) for key in required):
        raise ValueError("Fixture is missing a required section.")
    return fixture


def request(*, text: str, caption: str, seed: int, ref: Path | None, settings: dict[str, Any]):
    from irodori_tts.inference_runtime import SamplingRequest

    return SamplingRequest(text=text, caption=caption, seed=seed, ref_wav=str(ref) if ref else None, no_ref=ref is None, num_steps=int(settings["num_steps"]), cfg_scale_text=float(settings["cfg_scale_text"]), cfg_scale_caption=float(settings["cfg_scale_caption"]), cfg_scale_speaker=float(settings["cfg_scale_speaker"]), cfg_guidance_mode=str(settings["cfg_guidance_mode"]), t_schedule_mode=str(settings["t_schedule_mode"]), sway_coeff=float(settings["sway_coeff"]))


def synthesize(runtime: Any, save_wav: Any, path: Path, item: dict[str, Any], seed: int, ref: Path | None, settings: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    result = runtime.synthesize(request(text=str(item["text"]), caption=str(item["caption"]), seed=seed, ref=ref, settings=settings))
    save_wav(path, result.audio, result.sample_rate)
    return {"wav": str(path), "sha256": sha256(path), "details": wav_details(path), "used_seed": result.used_seed, "caption": item["caption"]}


def quiet_boundaries(source: Path, segment_texts: list[str]) -> list[int]:
    """Find low-energy cut points near text-length-proportional segment boundaries."""
    with wave.open(str(source), "rb") as reader:
        if reader.getsampwidth() != 2 or reader.getnchannels() != 1:
            raise ValueError("Only mono 16-bit WAV files can be segmented.")
        rate = reader.getframerate()
        samples = array("h", reader.readframes(reader.getnframes()))
    frame = max(1, round(rate * 0.05))
    energies = [math.sqrt(sum(sample * sample for sample in samples[index:index + frame]) / max(1, len(samples[index:index + frame]))) for index in range(0, len(samples), frame)]
    total_weight = sum(len(text) for text in segment_texts)
    boundaries: list[int] = []
    consumed = 0
    for text in segment_texts[:-1]:
        consumed += len(text)
        expected = round(len(energies) * consumed / total_weight)
        lower = max((boundaries[-1] // frame if boundaries else 0) + round(rate * 2.0 / frame), expected - round(rate * 2.5 / frame))
        upper = min(len(energies) - round(rate * 2.0 / frame), expected + round(rate * 2.5 / frame))
        selected = min(range(lower, upper + 1), key=energies.__getitem__)
        boundaries.append(selected * frame)
    return boundaries


def split_primary(source: Path, segments: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    with wave.open(str(source), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(reader.getnframes())
    boundaries = [0, *quiet_boundaries(source, [str(segment["text"]) for segment in segments]), params.nframes]
    paths: list[Path] = []
    bytes_per_frame = params.nchannels * params.sampwidth
    for segment, start, end in zip(segments, boundaries[:-1], boundaries[1:], strict=True):
        path = output_dir / f"{segment['id']}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as writer:
            writer.setparams(params)
            writer.writeframes(frames[start * bytes_per_frame:end * bytes_per_frame])
        paths.append(path)
    return paths


def run(args: argparse.Namespace) -> int:
    fixture_path = args.fixture.resolve()
    fixture = read_fixture(fixture_path)
    destination = args.output_dir.resolve()
    if args.dry_run:
        print(json.dumps({"fixture": str(fixture_path), "output": str(destination)}, ensure_ascii=False))
        return 0
    if destination.exists():
        raise SystemExit(f"Refusing to overwrite: {destination}")
    engine_dir = args.engine_dir.resolve()
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))
    from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey, download_hf_checkpoint, save_wav

    settings = fixture["settings"]
    checkpoint = download_hf_checkpoint(str(fixture["checkpoint"]))
    key = RuntimeKey(checkpoint=checkpoint, model_device=str(settings["model_device"]), codec_repo="Aratako/Semantic-DACVAE-Japanese-32dim", model_precision=str(settings["model_precision"]), codec_device=str(settings["codec_device"]), codec_precision=str(settings["codec_precision"]))
    runtime = InferenceRuntime.from_key(key)
    manifest: dict[str, Any] = {"fixture": str(fixture_path), "fixture_sha256": sha256(fixture_path), "engine_revision": git_revision(engine_dir), "settings": settings, "runs": []}
    primary = destination / "primary" / "full-performance.wav"
    manifest["runs"].append({"kind": "primary-single-pass", **synthesize(runtime, save_wav, primary, fixture["primary_performance"], int(fixture["primary_seed"]), None, settings)})
    segments = fixture["segments"]
    paths = split_primary(primary, segments, destination / "primary-segments")
    for segment, path in zip(segments, paths, strict=True):
        manifest["runs"].append({"kind": "primary-segment", "id": segment["id"], "source": str(primary), "wav": str(path), "sha256": sha256(path), "details": wav_details(path)})
    neutral = fixture["neutral_probe"]
    for segment, ref in zip(segments, paths, strict=True):
        path = destination / "from-segment" / f"{segment['id']}-to-neutral.wav"
        manifest["runs"].append({"kind": "neutral-from-primary-segment", "reference": segment["id"], **synthesize(runtime, save_wav, path, neutral, int(neutral["seed"]), ref, settings)})
    path = destination / "from-primary" / "neutral.wav"
    manifest["runs"].append({"kind": "neutral-from-full-primary", **synthesize(runtime, save_wav, path, neutral, int(neutral["seed"]), primary, settings)})
    for item in fixture["emotion_probes"]:
        path = destination / "from-primary" / f"{item['id']}.wav"
        manifest["runs"].append({"kind": "emotion-from-full-primary", "id": item["id"], **synthesize(runtime, save_wav, path, item, int(item["seed"]), primary, settings)})
    (destination / "run-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Output: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run(arguments()))

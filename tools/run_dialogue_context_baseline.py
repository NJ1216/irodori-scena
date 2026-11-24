#!/usr/bin/env python3
"""Generate a fixed-reference three-speaker dialogue context listening test.

The parent process uses the configured Irodori-TTS environment. The worker
loads one runtime, generates A/B/C reference WAVs once, then reuses those WAVs
for every dialogue line and scenario.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

from baseline_utils import git_revision, sha256, wav_details


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENGINE_DIR = PROJECT_ROOT.parent / "_ExternalRepos" / "Irodori-TTS"
DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "inference" / "dialogue-context-fixture.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fixed-reference A/B/C dialogue caption-context baseline.")
    parser.add_argument("--engine-dir", type=Path, default=DEFAULT_ENGINE_DIR)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--allow-existing-output",
        action="store_true",
        help="Add only new scenario directories to an existing output directory.",
    )
    parser.add_argument(
        "--reference-wav",
        action="append",
        default=[],
        metavar="SPEAKER=PATH",
        help="Reuse a fixed reference WAV for a speaker instead of generating it.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Fixture not found: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Fixture is not valid JSON: {path}: {error}") from error
    required = ("checkpoint", "sway_16", "speakers", "scene_context", "dialogue", "scenarios")
    missing = [key for key in required if not fixture.get(key)]
    if missing:
        raise SystemExit(f"Fixture is missing: {', '.join(missing)}")
    speaker_ids = {speaker.get("id") for speaker in fixture["speakers"]}
    if None in speaker_ids or len(speaker_ids) != len(fixture["speakers"]):
        raise SystemExit("Every speaker needs a unique id.")
    for line in fixture["dialogue"]:
        if line.get("speaker") not in speaker_ids or not line.get("text") or not line.get("stage_direction"):
            raise SystemExit("Every dialogue line needs a known speaker, text, and stage_direction.")
        if "seed" in line and not isinstance(line["seed"], int):
            raise SystemExit("A dialogue line seed must be an integer when provided.")
    for scenario in fixture["scenarios"]:
        if "text_prefix" in scenario and not isinstance(scenario["text_prefix"], str):
            raise SystemExit("A scenario text_prefix must be a string when provided.")
        line_prefixes = scenario.get("line_text_prefixes", {})
        if not isinstance(line_prefixes, dict) or not all(
            isinstance(line_id, str) and isinstance(prefix, str) for line_id, prefix in line_prefixes.items()
        ):
            raise SystemExit("Scenario line_text_prefixes must map line ids to strings.")
    return fixture


def concatenate_wavs(inputs: list[Path], output: Path, *, pause_seconds: float = 0.35) -> None:
    if not inputs:
        raise ValueError("At least one WAV is required to build a dialogue preview.")
    with wave.open(str(inputs[0]), "rb") as first:
        channels = first.getnchannels()
        sample_width = first.getsampwidth()
        sample_rate = first.getframerate()
        compression = first.getcomptype()
        if compression != "NONE":
            raise ValueError("Dialogue preview only supports uncompressed WAV files.")
    silence = b"\x00" * int(round(pause_seconds * sample_rate)) * channels * sample_width
    with wave.open(str(output), "wb") as merged:
        merged.setnchannels(channels)
        merged.setsampwidth(sample_width)
        merged.setframerate(sample_rate)
        for index, path in enumerate(inputs):
            with wave.open(str(path), "rb") as source:
                source_format = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                    source.getcomptype(),
                )
                expected_format = (channels, sample_width, sample_rate, compression)
                if source_format != expected_format:
                    raise ValueError(f"Cannot concatenate WAV with different format: {path}")
                merged.writeframes(source.readframes(source.getnframes()))
            if index < len(inputs) - 1:
                merged.writeframes(silence)


def output_directory(args: argparse.Namespace) -> Path:
    if args.output_dir is not None:
        return args.output_dir.resolve()
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return PROJECT_ROOT / "artifacts" / "inference" / "dialogue-context" / timestamp


def worker_command(args: argparse.Namespace, destination: Path) -> list[str]:
    command = [
        "uv",
        "run",
        "--no-sync",
        "python",
        str(Path(__file__).resolve()),
        "--worker",
        "--engine-dir",
        str(args.engine_dir.resolve()),
        "--fixture",
        str(args.fixture.resolve()),
        "--output-dir",
        str(destination),
    ]
    for reference_wav in args.reference_wav:
        speaker_id, raw_path = reference_wav.split("=", maxsplit=1)
        absolute_reference = Path(raw_path).expanduser().resolve()
        command.extend(["--reference-wav", f"{speaker_id}={absolute_reference}"])
    if args.allow_existing_output:
        command.append("--allow-existing-output")
    return command


def parse_reference_wavs(values: list[str], *, valid_speakers: set[str]) -> dict[str, Path]:
    overrides: dict[str, Path] = {}
    for value in values:
        try:
            speaker_id, raw_path = value.split("=", maxsplit=1)
        except ValueError as error:
            raise SystemExit(f"Invalid --reference-wav value {value!r}; expected SPEAKER=PATH.") from error
        if speaker_id not in valid_speakers:
            raise SystemExit(f"Unknown speaker in --reference-wav: {speaker_id}")
        if speaker_id in overrides:
            raise SystemExit(f"Duplicate --reference-wav for speaker: {speaker_id}")
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"Reference WAV not found for {speaker_id}: {path}")
        overrides[speaker_id] = path
    return overrides


def run_parent(args: argparse.Namespace) -> int:
    fixture = load_fixture(args.fixture.resolve())
    engine_dir = args.engine_dir.resolve()
    if not (engine_dir / "infer.py").is_file():
        raise SystemExit(f"Irodori-TTS infer.py not found under: {engine_dir}")
    if shutil.which("uv") is None:
        raise SystemExit("uv is required to invoke the configured Irodori-TTS environment.")
    destination = output_directory(args)
    command = worker_command(args, destination)
    if args.dry_run:
        reused_references = parse_reference_wavs(
            args.reference_wav,
            valid_speakers={speaker["id"] for speaker in fixture["speakers"]},
        )
        reference_count = len(fixture["speakers"]) - len(reused_references)
        dialogue_count = len(fixture["dialogue"]) * len(fixture["scenarios"])
        print(
            "The worker loads one runtime, then generates "
            f"{reference_count} reference WAVs and {dialogue_count} dialogue WAVs."
        )
        if reused_references:
            print("Reused references: " + ", ".join(sorted(reused_references)))
        print("$ " + " ".join(command))
        print("Scenarios: " + ", ".join(item["id"] for item in fixture["scenarios"]))
        return 0
    result = subprocess.run(command, cwd=engine_dir, check=False)
    return result.returncode


def sampling_request(*, text: str, caption: str | None, seed: int, ref_wav: Path | None, settings: dict[str, Any]):
    from irodori_tts.inference_runtime import SamplingRequest

    return SamplingRequest(
        text=text,
        caption=caption,
        ref_wav=str(ref_wav) if ref_wav is not None else None,
        no_ref=ref_wav is None,
        num_steps=int(settings["num_steps"]),
        cfg_scale_text=float(settings["cfg_scale_text"]),
        cfg_scale_caption=float(settings["cfg_scale_caption"]),
        cfg_scale_speaker=float(settings["cfg_scale_speaker"]),
        cfg_guidance_mode=str(settings["cfg_guidance_mode"]),
        seed=seed,
        t_schedule_mode=str(settings["t_schedule_mode"]),
        sway_coeff=float(settings["sway_coeff"]),
    )


def caption_for(scenario: dict[str, Any], line: dict[str, Any], scene_context: str) -> str | None:
    sections: list[str] = []
    if scenario["include_scene_context"]:
        sections.append(scene_context)
    if scenario["include_stage_directions"]:
        sections.append(line["stage_direction"])
    return "\n".join(sections) or None


def add_result(
    manifest: dict[str, Any],
    *,
    kind: str,
    identifier: str,
    output_wav: Path,
    result: Any,
    caption: str | None,
    speaker_id: str | None,
) -> None:
    manifest["runs"].append(
        {
            "kind": kind,
            "id": identifier,
            "speaker": speaker_id,
            "caption": caption,
            "used_seed": result.used_seed,
            "stage_timings_seconds": dict(result.stage_timings),
            "total_to_decode_seconds": result.total_to_decode,
            "wav": str(output_wav.relative_to(Path(manifest["output_dir"]))),
            "wav_sha256": sha256(output_wav),
            "wav_details": wav_details(output_wav),
        }
    )


def run_worker(args: argparse.Namespace) -> int:
    engine_dir = args.engine_dir.resolve()
    if str(engine_dir) not in sys.path:
        sys.path.insert(0, str(engine_dir))
    from irodori_tts.inference_runtime import InferenceRuntime, RuntimeKey, download_hf_checkpoint, save_wav

    fixture_path = args.fixture.resolve()
    fixture = load_fixture(fixture_path)
    reference_overrides = parse_reference_wavs(
        args.reference_wav,
        valid_speakers={speaker["id"] for speaker in fixture["speakers"]},
    )
    destination = output_directory(args)
    if destination.exists():
        if not args.allow_existing_output:
            raise SystemExit(f"Output directory already exists: {destination}")
        existing_scenarios = [
            scenario["id"] for scenario in fixture["scenarios"] if (destination / "dialogue" / scenario["id"]).exists()
        ]
        if existing_scenarios:
            raise SystemExit("Refusing to overwrite existing scenario output: " + ", ".join(existing_scenarios))
    destination.mkdir(parents=True, exist_ok=args.allow_existing_output)
    settings = fixture["sway_16"]
    checkpoint = download_hf_checkpoint(str(fixture["checkpoint"]))
    runtime = InferenceRuntime.from_key(
        RuntimeKey(
            checkpoint=checkpoint,
            model_device=str(settings["model_device"]),
            codec_repo="Aratako/Semantic-DACVAE-Japanese-32dim",
            model_precision=str(settings["model_precision"]),
            codec_device=str(settings["codec_device"]),
            codec_precision=str(settings["codec_precision"]),
        )
    )
    manifest: dict[str, Any] = {
        "suite_version": fixture["suite_version"],
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "output_dir": str(destination),
        "fixture_path": str(fixture_path),
        "fixture_sha256": sha256(fixture_path),
        "engine_dir": str(engine_dir),
        "engine_git_revision": git_revision(engine_dir),
        "checkpoint": str(checkpoint),
        "platform": platform.platform(),
        "python": sys.version,
        "settings": settings,
        "runs": [],
    }
    references: dict[str, Path] = {}
    for speaker in fixture["speakers"]:
        speaker_id = speaker["id"]
        if speaker_id in reference_overrides:
            output_wav = reference_overrides[speaker_id]
            references[speaker_id] = output_wav
            manifest["runs"].append(
                {
                    "kind": "speaker-reference-reused",
                    "id": speaker_id,
                    "speaker": speaker_id,
                    "source_wav": str(output_wav),
                    "wav_sha256": sha256(output_wav),
                    "wav_details": wav_details(output_wav),
                }
            )
            print(f"Reused speaker reference: {output_wav}", flush=True)
            continue
        output_wav = destination / "speaker-references" / f"{speaker['id']}.wav"
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        result = runtime.synthesize(
            sampling_request(
                text=speaker["reference_text"],
                caption=speaker["reference_caption"],
                seed=int(speaker["seed"]),
                ref_wav=None,
                settings=settings,
            )
        )
        save_wav(output_wav, result.audio, result.sample_rate)
        references[speaker_id] = output_wav
        add_result(
            manifest,
            kind="speaker-reference",
            identifier=speaker["id"],
            output_wav=output_wav,
            result=result,
            caption=speaker["reference_caption"],
            speaker_id=speaker_id,
        )
        print(f"Generated speaker reference: {output_wav}", flush=True)

    for scenario in fixture["scenarios"]:
        scenario_wavs: list[Path] = []
        for index, line in enumerate(fixture["dialogue"], start=1):
            caption = caption_for(scenario, line, str(fixture["scene_context"]))
            seed = int(line.get("seed", 2026081500 + index))
            text = (
                str(scenario.get("text_prefix", ""))
                + str(scenario.get("line_text_prefixes", {}).get(line["id"], ""))
                + line["text"]
            )
            output_wav = destination / "dialogue" / scenario["id"] / f"{line['id']}-{line['speaker']}.wav"
            output_wav.parent.mkdir(parents=True, exist_ok=True)
            result = runtime.synthesize(
                sampling_request(
                    text=text,
                    caption=caption,
                    seed=seed,
                    ref_wav=references[line["speaker"]],
                    settings=settings,
                )
            )
            save_wav(output_wav, result.audio, result.sample_rate)
            scenario_wavs.append(output_wav)
            add_result(
                manifest,
                kind="dialogue",
                identifier=f"{scenario['id']}/{line['id']}",
                output_wav=output_wav,
                result=result,
                caption=caption,
                speaker_id=line["speaker"],
            )
            print(f"Generated dialogue: {output_wav}", flush=True)
        preview_wav = destination / "dialogue" / scenario["id"] / "full-dialogue.wav"
        concatenate_wavs(scenario_wavs, preview_wav)
        manifest["runs"].append(
            {
                "kind": "dialogue-preview",
                "id": scenario["id"],
                "wav": str(preview_wav.relative_to(destination)),
                "wav_sha256": sha256(preview_wav),
                "wav_details": wav_details(preview_wav),
                "line_pause_seconds": 0.35,
            }
        )
        print(f"Generated dialogue preview: {preview_wav}", flush=True)

    manifest_path = destination / "run-manifest.json"
    if manifest_path.exists():
        scenario_ids = "-".join(str(scenario["id"]) for scenario in fixture["scenarios"])
        manifest_path = destination / f"run-manifest-{scenario_ids}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Manifest: {manifest_path}")
    return 0


def main() -> int:
    args = parse_args()
    return run_worker(args) if args.worker else run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())

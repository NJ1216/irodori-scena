#!/usr/bin/env python3
"""Run the fixed-input Sway 16 caption-context listening baseline.

This script deliberately invokes the upstream Irodori-TTS CLI as a separate
process. It does not modify the upstream checkout, and each WAV is written
directly under this Studio repository's ignored artifacts directory.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from baseline_utils import git_revision, sha256, wav_details


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENGINE_DIR = PROJECT_ROOT.parent / "_ExternalRepos" / "Irodori-TTS"
DEFAULT_FIXTURE = PROJECT_ROOT / "tests" / "inference" / "caption-context-fixture.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the fixed-input Sway 16 caption-context listening baseline.")
    parser.add_argument(
        "--engine-dir",
        type=Path,
        default=DEFAULT_ENGINE_DIR,
        help="Irodori-TTS checkout. The sibling checkout is a development-only default.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="JSON fixture containing the fixed utterance and caption conditions.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Destination for WAVs, logs, and run-manifest.json.",
    )
    parser.add_argument(
        "--ref-wav",
        type=Path,
        default=None,
        help="Optional WAV for the required reference-voice follow-up run.",
    )
    parser.add_argument(
        "--include-linear-40",
        action="store_true",
        help="Also run Linear 40 for a quality comparison; Sway 16 remains the primary run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the fixture and print commands without loading a model or writing files.",
    )
    return parser.parse_args()


def load_fixture(path: Path) -> dict[str, Any]:
    try:
        fixture = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SystemExit(f"Fixture not found: {path}") from error
    except json.JSONDecodeError as error:
        raise SystemExit(f"Fixture is not valid JSON: {path}: {error}") from error

    fixed_input = fixture.get("fixed_input")
    conditions = fixture.get("conditions")
    sway = fixture.get("sway_16")
    if not isinstance(fixed_input, dict) or not fixed_input.get("text"):
        raise SystemExit("Fixture must include fixed_input.text.")
    if not isinstance(fixed_input.get("seed"), int):
        raise SystemExit("Fixture must include fixed_input.seed as an integer.")
    if not isinstance(conditions, list) or not conditions:
        raise SystemExit("Fixture must include at least one condition.")
    if not isinstance(sway, dict):
        raise SystemExit("Fixture must include sway_16 settings.")
    for condition in conditions:
        if not isinstance(condition, dict) or not condition.get("id"):
            raise SystemExit("Every condition must include an id.")
        sections = condition.get("caption_sections")
        if not isinstance(sections, list) or not all(isinstance(item, str) and item for item in sections):
            raise SystemExit(f"Condition {condition.get('id', '<unknown>')} needs caption_sections.")
    return fixture


def command_for(
    *,
    engine_dir: Path,
    fixture: dict[str, Any],
    settings: dict[str, Any],
    condition: dict[str, Any],
    output_wav: Path,
    ref_wav: Path | None,
) -> list[str]:
    fixed_input = fixture["fixed_input"]
    command = [
        "uv",
        "run",
        "--no-sync",
        "python",
        "infer.py",
        "--hf-checkpoint",
        str(fixture["checkpoint"]),
        "--text",
        str(fixed_input["text"]),
        "--caption",
        "\n".join(condition["caption_sections"]),
        "--output-wav",
        str(output_wav),
        "--seed",
        str(fixed_input["seed"]),
        "--num-steps",
        str(settings["num_steps"]),
        "--t-schedule-mode",
        str(settings["t_schedule_mode"]),
        "--sway-coeff",
        str(settings.get("sway_coeff", -1.0)),
        "--cfg-scale-text",
        str(settings["cfg_scale_text"]),
        "--cfg-scale-caption",
        str(settings["cfg_scale_caption"]),
        "--cfg-scale-speaker",
        str(settings["cfg_scale_speaker"]),
        "--cfg-guidance-mode",
        str(settings["cfg_guidance_mode"]),
        "--model-device",
        str(settings["model_device"]),
        "--codec-device",
        str(settings["codec_device"]),
        "--model-precision",
        str(settings["model_precision"]),
        "--codec-precision",
        str(settings["codec_precision"]),
        "--show-timings",
    ]
    if ref_wav is None:
        command.append("--no-ref")
    else:
        command.extend(["--ref-wav", str(ref_wav)])
    return command


def command_text(command: list[str]) -> str:
    return " ".join(subprocess.list2cmdline([part]) for part in command)


def settings_for_linear_40(sway: dict[str, Any]) -> dict[str, Any]:
    return {**sway, "num_steps": 40, "t_schedule_mode": "linear"}


def main() -> int:
    args = parse_args()
    fixture = load_fixture(args.fixture.resolve())
    engine_dir = args.engine_dir.resolve()
    ref_wav = args.ref_wav.resolve() if args.ref_wav is not None else None
    if not args.dry_run:
        if not (engine_dir / "infer.py").is_file():
            raise SystemExit(f"Irodori-TTS infer.py not found under: {engine_dir}")
        if shutil.which("uv") is None:
            raise SystemExit("uv is required to invoke the configured Irodori-TTS environment.")
        if ref_wav is not None and not ref_wav.is_file():
            raise SystemExit(f"Reference WAV not found: {ref_wav}")

    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir is not None
        else PROJECT_ROOT / "artifacts" / "inference" / "caption-context" / timestamp
    )
    suites: list[tuple[str, dict[str, Any]]] = [("sway-16", fixture["sway_16"])]
    if args.include_linear_40:
        suites.append(("linear-40", settings_for_linear_40(fixture["sway_16"])))

    planned: list[dict[str, Any]] = []
    for suite_id, settings in suites:
        for condition in fixture["conditions"]:
            output_wav = output_dir / suite_id / f"{condition['id']}.wav"
            command = command_for(
                engine_dir=engine_dir,
                fixture=fixture,
                settings=settings,
                condition=condition,
                output_wav=output_wav,
                ref_wav=ref_wav,
            )
            planned.append(
                {
                    "suite": suite_id,
                    "condition": condition["id"],
                    "caption": "\n".join(condition["caption_sections"]),
                    "output_wav": str(output_wav),
                    "command": command,
                }
            )

    if args.dry_run:
        for item in planned:
            print(f"[{item['suite']} / {item['condition']}]\n{command_text(item['command'])}\n")
        return 0

    output_dir.mkdir(parents=True, exist_ok=False)
    manifest: dict[str, Any] = {
        "suite_version": fixture["suite_version"],
        "started_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fixture_path": str(args.fixture.resolve()),
        "fixture_sha256": sha256(args.fixture.resolve()),
        "engine_dir": str(engine_dir),
        "engine_git_revision": git_revision(engine_dir),
        "platform": platform.platform(),
        "python": sys.version,
        "reference_mode": "ref-wav" if ref_wav else "no-ref",
        "reference_wav": str(ref_wav) if ref_wav else None,
        "runs": [],
    }
    for item in planned:
        output_wav = Path(item["output_wav"])
        output_wav.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            item["command"],
            cwd=engine_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        log_path = output_wav.with_suffix(".log")
        log_path.write_text(
            "$ " + command_text(item["command"]) + "\n\n" + result.stdout + result.stderr,
            encoding="utf-8",
        )
        run: dict[str, Any] = {
            "suite": item["suite"],
            "condition": item["condition"],
            "caption": item["caption"],
            "command": item["command"],
            "return_code": result.returncode,
            "log": str(log_path.relative_to(output_dir)),
        }
        if result.returncode == 0 and output_wav.is_file():
            run["wav"] = str(output_wav.relative_to(output_dir))
            run["wav_sha256"] = sha256(output_wav)
            run["wav_details"] = wav_details(output_wav)
        manifest["runs"].append(run)
        (output_dir / "run-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if result.returncode != 0:
            print(f"Failed: {item['suite']} / {item['condition']}; see {log_path}")
            return result.returncode
        print(f"Generated: {output_wav}")

    print(f"Manifest: {output_dir / 'run-manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

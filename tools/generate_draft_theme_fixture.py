#!/usr/bin/env python3
"""Create one fresh production theme-suggestion fixture for the duration benchmark."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app import ThemeSuggestionRequest, suggest_theme_completion  # noqa: E402
from server.registry import deps  # noqa: E402
from tools.benchmark_production_draft import benchmark_cast  # noqa: E402


RANGES = {5: (293, 421), 30: (900, 1300), 60: (1600, 2200)}


def build_fixture(minutes: int, seed: int, output: Path, global_characters: Path) -> dict:
    characters = benchmark_cast(global_characters)
    selected = deps.resolve_default_llm()
    operation_id = f"theme-benchmark-{minutes}-{time.time_ns()}"
    previous_root = deps.ACTIVE_PROJECT_ROOT
    isolated_root = output.parent / f"theme-project-{minutes}m"
    deps.activate_project_root(isolated_root, persist=False)
    project = deps.default_project()
    project["characters"] = characters
    deps.write_project(project)
    request = ThemeSuggestionRequest(
        provider="scena-local", base_url="http://scena.local/v1", model=selected["model"],
        character_ids=[str(item["id"]) for item in characters], target_minutes=minutes, theme="",
    )
    deps.begin_llm_operation(operation_id, "テーマ提案ベンチ", request.provider, request.model)
    deps.DRAFT_LLM_THREAD_CONTEXT.job_id = operation_id
    capability = deps.build_direction_capability_profile(request)
    if capability.get("detectedMemoryGiB") is None and request.provider == "scena-local":
        capability.update({"contextCeiling": 32768, "effectiveContext": 32768})
    deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = capability
    started = time.perf_counter()
    try:
        theme = suggest_theme_completion(request, benchmark_seed=seed)
        usage = next((item["usage"] for item in deps.session_usage()["history"]
                      if item["id"] == operation_id), {})
    finally:
        deps.DRAFT_LLM_THREAD_CONTEXT.job_id = None
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None
        deps.activate_project_root(previous_root, persist=False)
        deps.stop_local_llm()
    lower, upper = RANGES[minutes]
    fixture = {
        "minutes": minutes, "theme": theme, "themeCharacters": len(theme),
        "requiredThemeCharacters": {"minimum": lower, "maximum": upper},
        "themeAccepted": lower <= len(theme) <= upper,
        "speechRate": 1.2, "targetCharacters": round(minutes * 360 * 1.2),
        "cast": characters, "seeds": {"root": seed, "theme": seed},
        "themeUsage": usage, "themeCalls": 1,
        "themeWallClockSeconds": round(time.perf_counter() - started, 3),
        "model": selected["model"],
        "modelFingerprint": selected.get("localMetadata", {}).get("fingerprint"),
        "modelRevision": selected.get("localMetadata", {}).get("revision"),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return fixture


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, choices=tuple(RANGES), required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--global-characters", type=Path,
                        default=ROOT / "scena-data/global-characters/characters.json")
    args = parser.parse_args()
    fixture = build_fixture(args.minutes, args.seed, args.output, args.global_characters)
    print(json.dumps({key: fixture[key] for key in (
        "minutes", "themeCharacters", "requiredThemeCharacters", "themeAccepted", "themeCalls"
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

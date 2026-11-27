#!/usr/bin/env python3
"""Run one isolated production draft job and measure its persisted script."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("SCENA_BENCHMARK_CODE_ROOT", Path(__file__).resolve().parents[2])).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app import DraftRequest, run_forward_draft_job  # noqa: E402
from server.registry import deps  # noqa: E402


DEMO_CHARACTERS = [
    {"id": "cast-a", "name": "紗季", "profile": "一人称: 私\n話し方: 穏やかだが言い淀む",
     "profileDetails": {}, "relations": [{"targetId": "cast-b", "address": "悠真"}]},
    {"id": "cast-b", "name": "悠真", "profile": "一人称: 僕\n話し方: 丁寧で率直",
     "profileDetails": {}, "relations": [{"targetId": "cast-a", "address": "紗季"}]},
]

CAST_NAMES = ("Riri", "葵", "橘 颯太")


def benchmark_cast(global_characters_path: Path) -> list[dict]:
    records = json.loads(global_characters_path.read_text(encoding="utf-8"))
    selected = [copy.deepcopy(item) for name in CAST_NAMES for item in records if item.get("name") == name]
    if [item.get("name") for item in selected] != list(CAST_NAMES):
        raise RuntimeError(f"Required global cast not found: {CAST_NAMES}")
    selected_ids = {str(item["id"]) for item in selected}
    for item in selected:
        item["scope"] = "project"
        details = item.get("profileDetails", {})
        relations = details.get("castRelations", {}) if isinstance(details, dict) else {}
        if isinstance(relations, dict):
            details["castRelations"] = {
                key: value for key, value in relations.items() if str(key) in selected_ids
            }
    return selected


def cast_projection(characters: list[dict]) -> list[dict]:
    return [{key: copy.deepcopy(item[key]) for key in ("id", "name", "profile", "profileDetails", "scope")
             if key in item} for item in characters]


def project_projection(project: dict, character_ids: set[str]) -> dict:
    return {
        "id": project.get("id"), "title": project.get("title"),
        "characters": cast_projection([
            item for item in project.get("characters", []) if str(item.get("id", "")) in character_ids
        ]),
        "scenes": copy.deepcopy(project.get("scenes", [])),
    }


def spoken(drafted: list[dict]) -> int:
    return sum(len(str(line.get("text", ""))) for chapter in drafted
               for line in chapter.get("dialogue", {}).get("lines", []))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minutes", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--variant", choices=("baseline", "adaptive"), required=True)
    parser.add_argument("--theme", default="雨の日に再会した旧友二人が、忘れていた約束を思い出し、新しい約束を交わす。")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--global-characters", type=Path,
                        default=ROOT / "scena-data/global-characters/characters.json")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    selected = deps.resolve_default_llm()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8")) if args.fixture else None
    characters = benchmark_cast(args.global_characters) if fixture else DEMO_CHARACTERS
    theme = str(fixture["theme"]) if fixture else args.theme
    minutes = int(fixture["minutes"]) if fixture else args.minutes
    seed = int(fixture["seeds"]["root"]) if fixture else args.seed
    request = DraftRequest(
        provider="scena-local", base_url="http://scena.local/v1", model=selected["model"],
        character_ids=[str(item["id"]) for item in characters], target_minutes=minutes, speech_rate=1.2,
        theme=theme,
    )
    job_id = f"production-draft-benchmark-{time.time_ns()}"
    deps.DRAFT_JOBS[job_id] = {
        "id": job_id, "status": "planning", "cancelRequested": False, "overallProgress": 0.0,
        "generatedCharacters": 0, "chunks": [], "appendedLines": 0, "estimatedSeconds": 0,
        "provider": request.provider, "model": request.model, "usedTokens": 0,
        "benchmarkSeed": seed,
        "benchmarkRequiredSourceSchema": args.variant == "adaptive",
        "tokenUsageAvailable": True, "performanceTextCorrections": 0,
    }
    previous_root = deps.ACTIVE_PROJECT_ROOT
    isolated_root = args.output / "isolated-project"
    deps.activate_project_root(isolated_root, persist=False)
    project = deps.default_project()
    project["id"] = f"benchmark-adaptive-context-{minutes}m"
    project["characters"] = characters
    deps.write_project(project)
    started = time.perf_counter()
    try:
        run_forward_draft_job(job_id, request, characters)
        saved_project = deps.read_project()
    finally:
        deps.activate_project_root(previous_root, persist=False)
        deps.stop_local_llm()
    job = deps.DRAFT_JOBS.pop(job_id)
    saved_scenes = [scene for scene in saved_project.get("scenes", []) if scene.get("lines")]
    drafted = [{"dialogue": {"lines": [{
        "text": line.get("text", ""), "character_id": line.get("characterId", ""),
        "development_id": line.get("developmentId", ""),
        "stage_direction": line.get("stageDirection", ""),
    } for line in scene.get("lines", [])]}} for scene in saved_scenes]
    target = max(160, round(minutes * 360 * request.speech_rate))
    history = job.get("dialogueBatchHistory", [])
    required_sources = [source for call in history for source in call.get("requiredSources", [])]
    completed_sources = [source for call in history for source in call.get("completedSources", [])]
    fallback_used = any(call.get("shrinkReasons") for call in history)
    ownership_errors = sum("unknown_source" in call.get("shrinkReasons", []) for call in history)
    accepted_characters = spoken(drafted)
    result = {
        "variant": args.variant, "model": selected["model"], "minutes": minutes, "seed": seed,
        "theme": theme, "inputCast": cast_projection(characters),
        "modelFingerprint": selected.get("localMetadata", {}).get("fingerprint"),
        "modelRevision": selected.get("localMetadata", {}).get("revision"),
        "targetCharacters": target,
        "generationTargetCharacters": ((target * 110 + 99) // 100 if args.variant == "adaptive" else target),
        "acceptedCharacters": accepted_characters, "dialogueCalls": int(job.get("dialogueAttempt", 0)),
        "llmCallsIncludingPlanning": job.get("llmCallCount", 0), "status": job.get("status"),
        "targetReached": accepted_characters >= target, "allSourcesCompleted": (
            bool(required_sources) and required_sources == completed_sources),
        "ownershipErrors": ownership_errors, "fallbackUsed": fallback_used,
        "quality": {
            "exactDuplicateLines": len([line.get("text", "") for chapter in drafted
                for line in chapter["dialogue"]["lines"]]) - len(set(line.get("text", "") for chapter in drafted
                for line in chapter["dialogue"]["lines"])),
            "directionCoverage": sum(bool(line.get("stage_direction")) for chapter in drafted
                for line in chapter["dialogue"]["lines"]) / max(1, sum(len(chapter["dialogue"]["lines"])
                for chapter in drafted)),
            "lineCount": sum(len(chapter["dialogue"]["lines"]) for chapter in drafted),
        },
        "normalAdaptiveSuccess": (
            accepted_characters >= target
            and bool(required_sources) and required_sources == completed_sources
            and ownership_errors == 0 and not fallback_used and not job.get("partialReason")
        ),
        "job": job, "drafted": drafted,
        "promptCastContext": job.get("castContext", []),
        "castContextAudit": job.get("castContextAudit", []),
        "castContextSummaryUsage": job.get("castContextSummaryUsage", {}),
        "savedProject": project_projection(saved_project, set(request.character_ids)),
        "wallClockSeconds": round(time.perf_counter() - started, 3),
    }
    (args.output / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "targetCharacters", "generationTargetCharacters", "acceptedCharacters", "dialogueCalls",
        "llmCallsIncludingPlanning", "status", "targetReached", "allSourcesCompleted",
        "ownershipErrors", "fallbackUsed", "normalAdaptiveSuccess", "wallClockSeconds")},
        ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

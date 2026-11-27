#!/usr/bin/env python3
"""Run the fixed Gemma 4 AI-draft single-call/adaptive-batch comparison."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.app import DraftRequest, build_draft_capability_profile, generate_draft_dialogue  # noqa: E402
from server.registry import deps  # noqa: E402


BEATS = [
    "雨宿り中の二人が、閉店した喫茶店の軒先で偶然再会する。",
    "昔交わした約束を片方が覚えており、もう片方は思い出せず戸惑う。",
    "古い写真を手掛かりに、約束が町を出る前の再会だったと判明する。",
    "互いに連絡しなかった理由を正直に話し、責めずに受け止める。",
    "雨が弱まり、翌週同じ場所で続きを話す新しい約束を交わす。",
]
CAST = [
    {"cast": "A", "name": "紗季", "profile": "一人称: 私\n話し方: 穏やかだが言い淀む",
     "preferences": {"priority": "main"}, "relations": [{"target": "B", "address": "悠真"}]},
    {"cast": "B", "name": "悠真", "profile": "一人称: 僕\n話し方: 丁寧で率直",
     "preferences": {"priority": "main"}, "relations": [{"target": "A", "address": "紗季"}]},
]


def _usage(job: dict[str, Any]) -> dict[str, int]:
    usage = job.get("tokenUsage", {})
    return {
        "promptTokens": int(usage.get("inputTokens", 0)),
        "completionTokens": int(usage.get("outputTokens", 0)),
        "cachedTokens": int(usage.get("cachedInputTokens", 0)),
        "totalTokens": int(usage.get("totalTokens", 0)),
    }


def _quality(lines: list[dict[str, Any]], expected: list[str]) -> dict[str, Any]:
    sources = [str(line.get("development_id", "")) for line in lines]
    texts = [str(line.get("text", "")) for line in lines]
    directions = [line.get("integrated_direction") for line in lines]
    repeated = len(texts) - len(set(texts))
    return {
        "spokenCharacters": sum(len(text) for text in texts),
        "developmentCoverage": sum(source in sources for source in expected) / len(expected),
        "speakerConsistency": sum(line.get("character_id") in {"A", "B"} for line in lines) / max(1, len(lines)),
        "repeatedExactLines": repeated,
        "directionFieldRate": sum(isinstance(value, dict) and bool(value) for value in directions) / max(1, len(lines)),
        "lineCount": len(lines),
    }


def run_variant(request: DraftRequest, root: Path, variant: str, seed: int) -> dict[str, Any]:
    job_id = f"benchmark-{variant}"
    deps.DRAFT_JOBS[job_id] = {"id": job_id, "provider": request.provider, "model": request.model,
                               "usedTokens": 0, "tokenUsageAvailable": True}
    deps.begin_llm_operation(job_id, "AI台本生成ベンチ", request.provider, request.model)
    capability_characters = [
        {"id": "cast-a", "name": CAST[0]["name"]},
        {"id": "cast-b", "name": CAST[1]["name"]},
    ]
    profile = build_draft_capability_profile(request, capability_characters)
    profile.update({"contextCeiling": 32768, "effectiveContext": 32768,
                    "outputTokenLimit": 6144, "maxChunkCharacters": 5000})
    profile.pop("dialogueContext", None)
    deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = profile
    plan = {"story_bible": "現代日本の地方都市。二人は学生時代の友人。", "chapters": []}
    accepted: dict[str, Any] = {"lines": []}
    pending = list(range(len(BEATS)))
    batch_size = 1 if variant == "baseline" else 2
    calls = []
    started = time.perf_counter()
    while pending and len(calls) < len(BEATS) + 2:
        call_index = len(calls) + 1
        selected_indexes = pending[:batch_size]
        selected = [f"D1.{index + 1}|{BEATS[index]}" for index in selected_indexes]
        expected = [item.split("|", 1)[0] for item in selected]
        before = _usage(deps.DRAFT_JOBS[job_id])
        call_started = time.perf_counter()
        raw, loop_reason = generate_draft_dialogue(
            request, cast_context=CAST, plan=plan,
            chapter={"title": "雨の再会", "objective": "過去と向き合い次の約束を作る", "beats": selected,
                     "opening_state": "雨宿りを始める", "closing_state": "新しい約束をする"},
            chapter_index=0, requested_characters=300 * len(selected), remaining_characters=300 * len(selected),
            accepted_dialogue=accepted, continuity_state="", token_budget=6144,
            cast_alias_by_id={"cast-a": "A", "cast-b": "B"}, job_id=job_id,
            benchmark_seed=seed + call_index - 1,
            debug_response_path=root / f"{variant}-{call_index:02d}.txt")
        after = _usage(deps.DRAFT_JOBS[job_id])
        records = [line for line in raw.get("lines", []) if line.get("development_id") in expected]
        accepted["lines"].extend(records)
        calls.append({"batchSize": len(selected), "sources": expected, "mode": raw.get("_contract_mode"),
                      "partial": raw.get("_partial"), "loopReason": loop_reason,
                      "wallClockSeconds": round(time.perf_counter() - call_started, 3),
                      "promptTokens": after["promptTokens"] - before["promptTokens"],
                      "completionTokens": after["completionTokens"] - before["completionTokens"],
                      "cachedTokens": after["cachedTokens"] - before["cachedTokens"],
                      "acceptedSources": sorted(set(str(line.get("development_id")) for line in records)),
                      "ownershipRejections": sum(item.get("reason") == "unknown_owner"
                                                 for item in raw.get("_manifest", []))})
        covered = {int(source.split(".", 1)[1]) - 1 for source in calls[-1]["acceptedSources"]}
        pending = [index for index in pending if index not in covered]
        healthy = not raw.get("_partial") and not loop_reason and all(index in covered for index in selected_indexes)
        if variant != "baseline":
            batch_size = min(3, batch_size + 1) if healthy else max(1, batch_size - 1)
    job = deps.DRAFT_JOBS.pop(job_id)
    expected = [f"D1.{index + 1}" for index in range(len(BEATS))]
    return {"variant": variant, "seed": seed, "calls": calls, "usage": _usage(job),
            "wallClockSeconds": round(time.perf_counter() - started, 3),
            "context": deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile,
            "quality": _quality(accepted["lines"], expected), "lines": accepted["lines"]}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    selected = deps.resolve_default_llm()
    request = DraftRequest(provider="scena-local", base_url="http://scena.local/v1", model=selected["model"],
                           character_ids=["cast-a", "cast-b"], target_minutes=5,
                           theme="雨の日に再会した旧友二人が、忘れていた約束を思い出し、新しい約束を交わす。")
    try:
        baseline = run_variant(request, args.output, "baseline", args.seed)
        candidate = run_variant(request, args.output, "adaptive", args.seed)
    finally:
        deps.stop_local_llm()
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None
    baseline_input = baseline["usage"]["promptTokens"]
    candidate_input = candidate["usage"]["promptTokens"]
    report = {"model": selected["model"], "fingerprint": selected["localMetadata"]["fingerprint"],
              "revision": selected["localMetadata"]["revision"], "seed": args.seed,
              "sampling": {"temperature": 0.8, "thinking": False},
              "inputTokenReductionPercent": round((baseline_input - candidate_input) / max(1, baseline_input) * 100, 2),
              "baseline": baseline, "adaptive": candidate}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("model", "fingerprint", "seed", "inputTokenReductionPercent")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

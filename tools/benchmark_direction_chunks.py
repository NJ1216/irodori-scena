#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.direction_benchmark_core import (  # noqa: E402
    CANDIDATES,
    assess_cache_records,
    aggregate_call_records,
    build_fixtures,
    cache_microbench_jobs,
    call_identity,
    latin_square_jobs,
    prompt_boundaries,
    summarize,
)
from tools.direction_benchmark_runtime import (  # noqa: E402
    append_jsonl,
    completed_identities,
    execute_call,
    wait_for_clean_thermal,
)
from tools.benchmark_gemma4 import _build_thermal_probe  # noqa: E402

MODEL = "mlx-community--gemma-4-31b-it-nvfp4"


def _wait_for_benchmark_ready(args: argparse.Namespace, probe: Path) -> None:
    wait_log = args.output / "thermal-waits.jsonl"

    def observe(event: dict) -> None:
        append_jsonl(wait_log, event)
        thermal = event["thermal"]
        print(
            "thermal wait: "
            f"state={thermal.get('state')} lowPower={thermal.get('lowPowerMode')} "
            f"stable={event['consecutiveHealthySamples']}/{event['requiredHealthySamples']}",
            flush=True,
        )

    wait_for_clean_thermal(
        probe,
        poll_seconds=args.thermal_poll_seconds,
        stable_samples=args.thermal_stable_samples,
        timeout_seconds=(args.thermal_timeout_minutes * 60 if args.thermal_timeout_minutes else None),
        observe=observe,
    )


def _append_until_thermally_clean(args, probe, results_path, invoke) -> dict:
    """Run a call, retaining contaminated attempts and retrying after recovery."""
    while True:
        _wait_for_benchmark_ready(args, probe)
        record = invoke()
        append_jsonl(results_path, record)
        if record["status"] == "completed":
            return record
        print("thermal contamination recorded; waiting for stable recovery", flush=True)


def _load_tokenizer():
    from transformers import AutoTokenizer

    registry = json.loads((ROOT / "scena-data/llm-registry.json").read_text(encoding="utf-8"))
    card = next(item for item in registry.get("cards", []) if item.get("modelId") == MODEL)
    return AutoTokenizer.from_pretrained(card["localMetadata"]["path"], local_files_only=True, trust_remote_code=False)


def _cast_context(deps, fixture: dict):
    cast_ids = list(dict.fromkeys(item["characterId"] for item in fixture["lines"]))
    return deps.draft_cast_context(
        fixture["casts"],
        cast_alias_by_id={character_id: chr(65 + index) for index, character_id in enumerate(cast_ids)},
    )


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(args: argparse.Namespace) -> None:
    paths = [item for pattern in args.source for item in ROOT.glob(pattern)]
    payload = build_fixtures(paths)
    write_json(args.output, payload)
    print(f"prepared {len(payload['fixtures'])} fixtures: {payload['fixtureHash']}")


def metadata(fixture_hash: str) -> dict[str, object]:
    registry = json.loads((ROOT / "scena-data/llm-registry.json").read_text(encoding="utf-8"))
    card = next(item for item in registry.get("cards", []) if item.get("modelId") == MODEL)
    local = card.get("localMetadata", {})
    return {
        "provider": "scena-local",
        "model": MODEL,
        "modelFingerprint": local.get("fingerprint"),
        "modelRevision": local.get("revision"),
        "omlxVersion": local.get("omlxVersion"),
        "machine": platform.machine(),
        "macOS": platform.mac_ver()[0],
        "memoryGuard": card.get("settings", {}).get("memoryGuard"),
        "context": 32768,
        "promptProtocolVersion": "scena-direction-cache-first-v4",
        "fixtureHash": fixture_hash,
        "ssdCache": "disabled",
        "fingerprintPurpose": "diagnostic-only; does not control KV cache",
    }


def run(args: argparse.Namespace) -> None:
    os.environ["SCENA_DEV_MODE"] = "1"
    import server.app  # noqa: F401
    from server.modules.models import AiDirectionRequest
    from server.registry import deps

    fixture_payload = json.loads(args.fixtures.read_text(encoding="utf-8"))
    fixtures = fixture_payload["fixtures"]
    args.output.mkdir(parents=True, exist_ok=True)
    results_path = args.output / "results.jsonl"
    completed = completed_identities(results_path)
    write_json(args.output / "environment.json", metadata(fixture_payload["fixtureHash"]))
    request = AiDirectionRequest(
        provider="scena-local",
        model=MODEL,
        line_ids=["benchmark"],
        overwrite_existing=True,
        allowed_emojis=list(deps.IRODORI_EMOJIS),
    )
    probe = _build_thermal_probe(args.output)
    if probe is None:
        raise SystemExit("macOS thermal probe is required")
    _wait_for_benchmark_ready(args, probe)
    deps.load_local_llm(
        MODEL,
        settings={
            "contextLimit": 32768,
            "memoryGuard": "safe",
            "ttlSeconds": 3600,
            "thinking": False,
            "trustRemoteCode": False,
            "mtp": True,
        },
    )
    tokenizer = _load_tokenizer()
    boundaries = []
    for cast_count in (1, 2, 6):
        fixture = next(item for item in fixtures if item["castCount"] == cast_count)
        cast_context = _cast_context(deps, fixture)
        from tools.direction_benchmark_runtime import rows_for

        rows, before, after = rows_for(fixture["lines"], 0, 10)
        for order in ("production", "cache-first"):
            system, user = deps.build_direction_prompt(
                request, rows, before, after, cast_context, benchmark_prompt_order=order
            )
            boundaries.append(
                {"promptOrder": order, "castCount": cast_count, **prompt_boundaries(tokenizer, system, user)}
            )
    write_json(args.output / "prompt-boundaries.json", {"measurements": boundaries})
    jobs = latin_square_jobs(len(fixtures))
    if args.smoke:
        jobs = [(0, size) for size in CANDIDATES]
    for fixture_index, size in jobs:
        fixture = fixtures[fixture_index]
        deps.unload_local_llm()
        deps.load_local_llm(
            MODEL,
            settings={
                "contextLimit": 32768,
                "memoryGuard": "safe",
                "ttlSeconds": 3600,
                "thinking": False,
                "trustRemoteCode": False,
                "mtp": True,
            },
        )
        cast_context = _cast_context(deps, fixture)
        for chunk_index, offset in enumerate(range(0, len(fixture["lines"]), size)):
            identity = call_identity(
                suite="exploration",
                prompt_order=args.prompt_order,
                cast_count=fixture["castCount"],
                repetition=0,
                scenario="natural",
                fixture_id=fixture["id"],
                chunk_size=size,
                chunk_index=chunk_index,
            )
            if identity in completed:
                continue
            record = _append_until_thermally_clean(args, probe, results_path, lambda: execute_call(
                deps=deps,
                request=request,
                fixture=fixture,
                output=args.output,
                probe=probe,
                suite="exploration",
                prompt_order=args.prompt_order,
                repetition=0,
                scenario="natural",
                chunk_size=size,
                chunk_index=chunk_index,
                offset=offset,
                cast_context=cast_context,
            ))
            completed.add(record["identity"])
            print(f"{fixture['id']} size={size} chunk={chunk_index + 1}: {record['status']}")


def microbench(args: argparse.Namespace) -> None:
    os.environ["SCENA_DEV_MODE"] = "1"
    import server.app  # noqa: F401
    from server.modules.models import AiDirectionRequest
    from server.registry import deps

    fixture_payload = json.loads(args.fixtures.read_text(encoding="utf-8"))
    fixtures = fixture_payload["fixtures"]
    args.output.mkdir(parents=True, exist_ok=True)
    results_path = args.output / "cache-results.jsonl"
    completed = completed_identities(results_path)
    request = AiDirectionRequest(
        provider="scena-local",
        model=MODEL,
        line_ids=["benchmark"],
        overwrite_existing=True,
        allowed_emojis=list(deps.IRODORI_EMOJIS),
    )
    settings = {
        "contextLimit": 32768,
        "memoryGuard": "safe",
        "ttlSeconds": 3600,
        "thinking": False,
        "trustRemoteCode": False,
        "mtp": True,
    }
    probe = _build_thermal_probe(args.output)
    if probe is None:
        raise SystemExit("macOS thermal probe is required")
    _wait_for_benchmark_ready(args, probe)
    deps.load_local_llm(MODEL, settings=settings)
    from tools.direction_benchmark_runtime import rows_for

    tokenizer, boundaries = _load_tokenizer(), []
    for cast_count in (1, 2, 6):
        fixture = next(item for item in fixtures if item["castCount"] == cast_count)
        rows, before, after = rows_for(fixture["lines"], 0, 10)
        for order in ("production", "cache-first"):
            system, user = deps.build_direction_prompt(request, rows, before, after, _cast_context(deps, fixture),
                                                       benchmark_prompt_order=order)
            boundaries.append({"promptOrder": order, "castCount": cast_count,
                               **prompt_boundaries(tokenizer, system, user)})
    write_json(args.output / "prompt-boundaries.json", {"measurements": boundaries})
    for job in cache_microbench_jobs(args.repetitions):
        candidates = [item for item in fixtures if item["castCount"] == job["castCount"]]
        fixture = candidates[1] if job["scenario"] == "different-cast" and len(candidates) > 1 else candidates[0]
        offset = 10 if job["scenario"] in {"no-cache-next", "same-cast-next"} else 0
        identity = call_identity(
            suite="cache",
            prompt_order=job["promptOrder"],
            cast_count=job["castCount"],
            repetition=job["repetition"],
            scenario=job["scenario"],
            fixture_id=fixture["id"],
            chunk_size=10,
            chunk_index=offset // 10,
        )
        if identity in completed:
            continue
        if job["scenario"] in {"no-cache-first", "no-cache-next", "cold-first"}:
            deps.unload_local_llm()
            deps.load_local_llm(MODEL, settings=settings)
        record = _append_until_thermally_clean(args, probe, results_path, lambda: execute_call(
            deps=deps,
            request=request,
            fixture=fixture,
            output=args.output,
            probe=probe,
            suite="cache",
            prompt_order=job["promptOrder"],
            repetition=job["repetition"],
            scenario=job["scenario"],
            chunk_size=10,
            chunk_index=offset // 10,
            offset=offset,
            cast_context=_cast_context(deps, fixture),
        ))
        completed.add(record["identity"])
        print(f"cache {job['promptOrder']} casts={job['castCount']} {job['scenario']}: {record['status']}")


def report(args: argparse.Namespace) -> None:
    records = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines()]
    write_json(args.output, {"results": summarize(aggregate_call_records(records))})


def cache_report(args: argparse.Namespace) -> None:
    records = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines()]
    write_json(args.output, assess_cache_records(records))


def parsed_fields(raw: str) -> dict[str, dict[str, str]]:
    result = {}
    for line in raw.replace("\r", "").split("\n"):
        parts = [item.strip() for item in line.split("|")]
        if len(parts) < 2 or not parts[0].startswith("L"):
            continue
        values = {}
        for part in parts[1:]:
            key, separator, value = part.partition("=")
            if separator and key in {"emoji", "rate", "gap", "direction"}:
                values[key] = value
        if values:
            result[parts[0]] = values
    return result


def review(args: argparse.Namespace) -> None:
    from server.modules.direction_optimization import direction_evidence_passes

    fixture_payload = json.loads(args.fixtures.read_text(encoding="utf-8"))
    summary = json.loads(args.report.read_text(encoding="utf-8"))["results"]
    records = [json.loads(line) for line in args.results.read_text(encoding="utf-8").splitlines()]
    baseline = next(item for item in summary if item["chunkSize"] == 10)
    passing = [item for item in summary if direction_evidence_passes(item, baseline)]
    if not passing:
        raise SystemExit("30件の自動合格候補がないためreview packは作成しません。")
    candidate = min(passing, key=lambda item: (item["medianSeconds"], item["chunkSize"]))["chunkSize"]
    comparisons = []
    for fixture in fixture_payload["fixtures"]:
        outputs = {}
        for size in (10, candidate):
            identities = [str(row["identity"]) for row in records
                          if row.get("fixtureId") == fixture["id"] and row.get("chunkSize") == size
                          and row.get("status") == "completed"]
            paths = [args.raw / f"{identity}.txt" for identity in identities]
            outputs[size] = parsed_fields("\n".join(path.read_text(encoding="utf-8") for path in paths))
        for index, source in enumerate(fixture["lines"]):
            alias = f"L{index + 1}"
            if alias not in outputs[10] or alias not in outputs[candidate]:
                continue
            swap = int(fixture["sha256"][:8], 16) % 2 == index % 2
            pair = [outputs[10][alias], outputs[candidate][alias]]
            if swap:
                pair.reverse()
            comparisons.append(
                {
                    "id": f"AB-{len(comparisons) + 1:03d}",
                    "source": source,
                    "A": pair[0],
                    "B": pair[1],
                    "choice": "優劣・同等・双方不可",
                }
            )
            if len(comparisons) >= args.samples:
                break
        if len(comparisons) >= args.samples:
            break
    write_json(
        args.output,
        {
            "candidateLabelsHidden": True,
            "baselineChunkSize": 10,
            "candidateChunkSize": candidate,
            "comparisons": comparisons,
        },
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="SCENA production-path AI direction benchmark")
    commands = result.add_subparsers(required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--source", action="append", default=["userproject/*.scena/project.json"])
    prep.add_argument("--output", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/fixtures.json")
    prep.set_defaults(function=prepare)
    execute = commands.add_parser("run")
    execute.add_argument("--fixtures", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/fixtures.json")
    execute.add_argument("--output", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/run")
    execute.add_argument("--smoke", action="store_true")
    execute.add_argument("--thermal-note", default="")
    execute.add_argument("--prompt-order", choices=("production", "cache-first"), default="cache-first")
    _add_thermal_wait_arguments(execute)
    execute.set_defaults(function=run)
    cache = commands.add_parser("microbench")
    cache.add_argument("--fixtures", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/fixtures.json")
    cache.add_argument("--output", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/cache")
    cache.add_argument("--repetitions", type=int, default=3)
    _add_thermal_wait_arguments(cache)
    cache.set_defaults(function=microbench)
    summary = commands.add_parser("report")
    summary.add_argument("--results", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/run/results.jsonl")
    summary.add_argument("--output", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/report.json")
    summary.set_defaults(function=report)
    cache_summary = commands.add_parser("cache-report")
    cache_summary.add_argument("--results", type=Path,
                               default=ROOT / "artifacts/direction-benchmark-v2/cache/cache-results.jsonl")
    cache_summary.add_argument("--output", type=Path,
                               default=ROOT / "artifacts/direction-benchmark-v2/cache/report.json")
    cache_summary.set_defaults(function=cache_report)
    review_parser = commands.add_parser("review")
    review_parser.add_argument("--fixtures", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/fixtures.json")
    review_parser.add_argument("--report", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/report.json")
    review_parser.add_argument("--raw", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/run/raw")
    review_parser.add_argument("--results", type=Path,
                               default=ROOT / "artifacts/direction-benchmark-v2/run/results.jsonl")
    review_parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/direction-benchmark-v2/review-pack.json"
    )
    review_parser.add_argument("--samples", type=int, default=30)
    review_parser.set_defaults(function=review)
    return result


def _add_thermal_wait_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--thermal-poll-seconds", type=float, default=60.0)
    command.add_argument("--thermal-stable-samples", type=int, default=3)
    command.add_argument(
        "--thermal-timeout-minutes",
        type=float,
        default=0,
        help="0 waits indefinitely; Ctrl+C still stops safely",
    )


if __name__ == "__main__":
    options = parser().parse_args()
    options.function(options)

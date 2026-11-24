from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Iterable

CANDIDATES = (10, 20, 30, 50, 100)
FIELDS = ("emoji", "rate", "gap", "direction")
PROMPT_ORDERS = ("production", "cache-first")
CACHE_SCENARIOS = ("no-cache-first", "no-cache-next", "cold-first", "exact-repeat", "same-cast-next", "different-cast")


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def project_lines(project: dict[str, Any]) -> list[dict[str, Any]]:
    names = {str(item.get("id")): str(item.get("name", "?")) for item in project.get("characters", [])}
    return [
        {
            "name": names.get(str(line.get("characterId")), "?"),
            "characterId": str(line.get("characterId")),
            "text": str(line.get("text", "")),
            "rate": line.get("speechRate"),
            "gap": line.get("gapSeconds"),
            "stage": str(line.get("stageDirection", "")),
        }
        for scene in project.get("scenes", [])
        if isinstance(scene, dict)
        for line in scene.get("lines", [])
        if isinstance(line, dict)
        if str(line.get("text", "")).strip() and str(line.get("characterId", "")).strip()
    ]


def build_fixtures(project_paths: Iterable[Path], *, count: int = 6, size: int = 100) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for path in sorted(project_paths):
        try:
            project = json.loads(path.read_text(encoding="utf-8"))
            lines = project_lines(project)
        except (OSError, ValueError, TypeError):
            continue
        cast_ids = list(dict.fromkeys(line["characterId"] for line in lines))
        if len(lines) >= size and len(cast_ids) in {1, 2, 6}:
            casts = [item for item in project.get("characters", []) if str(item.get("id")) in cast_ids]
            sources.append(
                {
                    "hash": canonical_hash({"casts": casts, "lines": lines}),
                    "lines": lines,
                    "casts": casts,
                    "castCount": len(cast_ids),
                }
            )
    by_count = {cast_count: [item for item in sources if item["castCount"] == cast_count] for cast_count in (1, 2, 6)}
    if any(not items for items in by_count.values()):
        raise ValueError("1／2／6キャストそれぞれに100行以上ある既存台本が必要です。")
    fixtures = []
    for index in range(count):
        cast_count = (1, 2, 6)[index % 3]
        source = by_count[cast_count][(index // 3) % len(by_count[cast_count])]
        maximum_start = len(source["lines"]) - size
        start = ((index // 3) * 17) % (maximum_start + 1)
        rows = source["lines"][start : start + size]
        fixture = {"id": f"fixture-{index + 1:02d}", "castCount": cast_count, "casts": source["casts"], "lines": rows}
        fixture["sha256"] = canonical_hash(fixture)
        fixtures.append(fixture)
    payload = {"version": 2, "sourceHashes": [item["hash"] for item in sources], "fixtures": fixtures}
    payload["fixtureHash"] = canonical_hash(fixtures)
    return payload


def latin_square_jobs(fixture_count: int, candidates: tuple[int, ...] = CANDIDATES) -> list[tuple[int, int]]:
    return [
        (fixture, candidates[(position + fixture) % len(candidates)])
        for position in range(len(candidates))
        for fixture in range(fixture_count)
    ]


def call_identity(
    *,
    suite: str,
    prompt_order: str,
    cast_count: int,
    repetition: int,
    scenario: str,
    fixture_id: str,
    chunk_size: int,
    chunk_index: int,
) -> str:
    return canonical_hash(
        {
            "suite": suite,
            "promptOrder": prompt_order,
            "castCount": cast_count,
            "repetition": repetition,
            "scenario": scenario,
            "fixtureId": fixture_id,
            "chunkSize": chunk_size,
            "chunkIndex": chunk_index,
        }
    )


def cache_microbench_jobs(repetitions: int = 3) -> list[dict[str, Any]]:
    return [
        {"promptOrder": order, "castCount": cast_count, "repetition": repetition, "scenario": scenario}
        for repetition in range(repetitions)
        for cast_count in (1, 2, 6)
        for order in PROMPT_ORDERS
        for scenario in CACHE_SCENARIOS
    ]


def reusable_blocks(prefix_tokens: int, block_size: int = 1024) -> int:
    return max(0, prefix_tokens // block_size)


def prompt_boundaries(tokenizer: Any, system: str, user: dict[str, Any], *, block_size: int = 1024) -> dict[str, Any]:
    """Record exact chat-template boundaries without persisting token ids."""

    def count(value: dict[str, Any], *, generation: bool) -> int:
        rendered = tokenizer.apply_chat_template(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                },
            ],
            tokenize=False,
            add_generation_prompt=generation,
        )
        return len(tokenizer.encode(rendered, add_special_tokens=False))

    section_values = user
    if isinstance(user.get("sections"), list):
        section_values = {key: value for section in user["sections"] if isinstance(section, dict)
                          for key, value in section.items()}
    progressive: dict[str, Any] = {}
    offsets = {"system": count({}, generation=False)}
    for name in ("request_settings", "participating_casts", "lines"):
        if name in section_values:
            if "sections" in user:
                progressive.setdefault("sections", []).append({name: section_values[name]})
            else:
                progressive[name] = section_values[name]
        offsets[name] = count(progressive, generation=False)
    total = count(user, generation=True)
    return {
        "sectionEnds": offsets,
        "promptTokens": total,
        "blockSize": block_size,
        "reusableBlocksBeforeLines": reusable_blocks(offsets["participating_casts"], block_size),
    }


def production_score(
    raw: str, aliases: list[str], rows: list[dict[str, Any]], request: Any, allowed: set[str]
) -> dict[str, Any]:
    """Score only fields accepted by the production parser and patch validator."""
    from server.modules.ai_direction import _parse, _performance_patch, _record_values

    parsed = _parse(raw)
    by_alias = {str(row["alias"]): row for row in rows}
    accepted: dict[str, dict[str, Any]] = {}
    negative_rejections = 0
    accepted_by_field = {field: 0 for field in ("text", "speechRate", "gapSeconds", "stageDirection")}
    body_modifications = 0
    excessive_repetitions = 0
    for alias, parts in parsed.items():
        row = by_alias.get(alias)
        if row is None:
            continue
        values = _record_values(parts)
        patch = _performance_patch(request, row, values, allowed)
        if values.get("direction") and "stageDirection" not in patch:
            from server.modules.constants import prohibited_negative_tts_caption_reason

            negative_rejections += int(prohibited_negative_tts_caption_reason(values["direction"]) is not None)
        if patch:
            accepted[alias] = patch
            for field in accepted_by_field:
                accepted_by_field[field] += int(field in patch)
            if "text" in patch:
                from server.modules.llm_emoji_policy import strip_irodori_expression_emojis

                body_modifications += int(
                    strip_irodori_expression_emojis(str(patch["text"]))
                    != strip_irodori_expression_emojis(str(row["text"]))
                )
                excessive_repetitions += int(bool(re.search(r"([\U0001F000-\U0001FAFF])\1{3,}", str(patch["text"]))))
    base = score_response(raw, aliases)
    base.update(
        {
            "acceptedRows": len(accepted),
            "missingRows": len(set(aliases) - set(accepted)),
            "acceptedFields": sum(len(patch) for patch in accepted.values()),
            "acceptedByField": accepted_by_field,
            "bodyModifications": body_modifications,
            "excessiveRepetitions": excessive_repetitions,
            "negativeCaptionRejections": negative_rejections,
            "acceptedPatches": accepted,
        }
    )
    return base


def score_response(raw: str, aliases: list[str]) -> dict[str, Any]:
    expected = set(aliases)
    seen: list[str] = []
    valid_fields = 0
    prohibited_emoji = 0
    invalid_annotations = 0
    for line in raw.replace("\r", "").split("\n"):
        parts = [item.strip() for item in line.split("|")]
        if len(parts) < 2 or not re.fullmatch(r"L\d+", parts[0]):
            continue
        seen.append(parts[0])
        for item in parts[1:]:
            key, separator, value = item.partition("=")
            if separator and key in FIELDS and value.strip():
                valid_fields += 1
                if key == "direction" and re.search(r"[\U0001F000-\U0001FAFF]", value):
                    prohibited_emoji += 1
                if key == "direction" and ("(" in value or "（" in value):
                    invalid_annotations += 1
    duplicates = len(seen) - len(set(seen))
    unknown = len([alias for alias in seen if alias not in expected])
    present = expected.intersection(seen)
    return {
        "expectedRows": len(expected),
        "acceptedRows": len(present),
        "missingRows": len(expected - present),
        "duplicateAliases": duplicates,
        "ownershipErrors": unknown,
        "validFields": valid_fields,
        "validFieldAcceptanceRate": valid_fields / (len(expected) * len(FIELDS)) if expected else 0,
        "prohibitedEmoji": prohibited_emoji,
        "invalidAnnotations": invalid_annotations,
    }


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def summarize(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries = []
    for size in CANDIDATES:
        group = [row for row in records if row.get("chunkSize") == size and row.get("status") == "completed"]
        seconds = [float(row["wallSeconds"]) for row in group]
        scores = [row["score"] for row in group]
        metric_keys = ("prompt_tokens", "completion_tokens", "cached_tokens", "peak_memory_bytes")
        metrics = {key: sum(float(row.get("metrics", {}).get(key, 0)) for row in group) for key in metric_keys}
        summaries.append(
            {
                "chunkSize": size,
                "sampleCount": len(group),
                "medianSeconds": statistics.median(seconds) if seconds else None,
                "p95Seconds": percentile(seconds, 0.95),
                "calls": sum(int(row.get("calls", 0)) for row in group),
                "ownershipErrors": sum(item["ownershipErrors"] for item in scores),
                "constraintViolations": sum(item["prohibitedEmoji"] + item["invalidAnnotations"] for item in scores),
                "completionRate": (
                    sum(item["acceptedRows"] for item in scores) / sum(item["expectedRows"] for item in scores)
                    if scores
                    else 0
                ),
                "missingRows": sum(item["missingRows"] for item in scores),
                "duplicateAliases": sum(item["duplicateAliases"] for item in scores),
                "prohibitedEmoji": sum(item["prohibitedEmoji"] for item in scores),
                "invalidAnnotations": sum(item["invalidAnnotations"] for item in scores),
                "validFieldAcceptanceRate": (
                    sum(item["validFields"] for item in scores)
                    / sum(item["expectedRows"] * len(FIELDS) for item in scores)
                    if scores
                    else 0
                ),
                "qualityNonDegraded": bool(
                    scores
                    and all(
                        item["ownershipErrors"] == 0
                        and item["prohibitedEmoji"] == 0
                        and item["invalidAnnotations"] == 0
                        for item in scores
                    )
                ),
                **metrics,
            }
        )
    return summaries


def aggregate_call_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_identity: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(records):
        identity = str(row.get("identity") or f"legacy-{index}")
        by_identity.setdefault(identity, []).append(row)
    records = [
        next((row for row in reversed(attempts) if row.get("status") == "completed"), attempts[-1])
        for attempts in by_identity.values()
    ]
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in records:
        if row.get("suite") == "exploration":
            groups.setdefault((str(row.get("fixtureId")), int(row.get("chunkSize", 0))), []).append(row)
    jobs = []
    for (fixture_id, size), calls in groups.items():
        timing_calls = [call for call in calls if call.get("status") == "completed"]
        scores = [call.get("score", {}) for call in calls if isinstance(call.get("score"), dict)]
        metrics: dict[str, float] = {}
        for call in timing_calls:
            for key, value in call.get("metrics", {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metrics[key] = (
                        max(metrics.get(key, 0), value) if key == "peak_memory_bytes" else metrics.get(key, 0) + value
                    )
        expected = sum(int(score.get("expectedRows", 0)) for score in scores)
        accepted = sum(int(score.get("acceptedRows", 0)) for score in scores)
        jobs.append(
            {
                "fixtureId": fixture_id,
                "chunkSize": size,
                "status": "completed"
                if calls and all(call.get("status") == "completed" for call in calls)
                else "incomplete",
                "wallSeconds": sum(float(call.get("wallSeconds", 0)) for call in timing_calls),
                "calls": len(timing_calls),
                "timingCallCount": len(timing_calls),
                "qualityCallCount": len(scores),
                "missingTimingCallCount": len(calls) - len(timing_calls),
                "metrics": metrics,
                "score": {
                    "expectedRows": expected,
                    "acceptedRows": accepted,
                    "missingRows": sum(int(score.get("missingRows", 0)) for score in scores),
                    "duplicateAliases": sum(int(score.get("duplicateAliases", 0)) for score in scores),
                    "ownershipErrors": sum(int(score.get("ownershipErrors", 0)) for score in scores),
                    "validFields": sum(int(score.get("acceptedFields", 0)) for score in scores),
                    "prohibitedEmoji": sum(int(score.get("prohibitedEmoji", 0)) for score in scores),
                    "invalidAnnotations": sum(int(score.get("invalidAnnotations", 0)) for score in scores),
                },
            }
        )
    return jobs


def assess_cache_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_identity: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(records):
        by_identity.setdefault(str(row.get("identity") or f"legacy-{index}"), []).append(row)
    records = [
        next((row for row in reversed(attempts) if row.get("status") == "completed"), attempts[-1])
        for attempts in by_identity.values()
    ]
    checks = []
    for row in records:
        if row.get("scenario") not in {"exact-repeat", "same-cast-next", "different-cast"}:
            continue
        metrics = row.get("metrics", {})
        cached, block = metrics.get("cached_tokens"), metrics.get("cache_block_size")
        positive = isinstance(cached, int) and cached > 0
        checks.append({"identity": row.get("identity"), "prefixMatch": metrics.get("prefix_hits", 0) > 0,
                       "cacheUsed": positive, "cachedTokenBlockAligned":
                       (isinstance(block, int) and cached % block == 0) if positive else None,
                       "ssdWritesZero": metrics.get("ssd_saves") == 0,
                       "cachedTokens": cached, "blockSize": block,
                       "prefillSeconds": metrics.get("prefill_duration"),
                       "hotCacheEvictions": metrics.get("hot_cache_evictions")})
    aligned = [row["cachedTokenBlockAligned"] for row in checks if row["cacheUsed"]]
    return {"checks": checks, "allBlockAligned": bool(aligned) and all(aligned),
            "allSsdWritesZero": bool(checks) and all(row["ssdWritesZero"] for row in checks)}

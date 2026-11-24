from __future__ import annotations

import json
import platform
from typing import Any

from server.registry import deps

DIRECTION_CHUNK_CANDIDATES = (10, 20, 30, 50, 100)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def direction_evidence_passes(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    """Apply the production gate to one measured acting chunk size."""
    size = candidate.get("chunkSize")
    samples = candidate.get("sampleCount")
    median = _number(candidate.get("medianSeconds"))
    p95 = _number(candidate.get("p95Seconds"))
    base_median = _number(baseline.get("medianSeconds"))
    base_p95 = _number(baseline.get("p95Seconds"))
    acceptance = _number(candidate.get("validFieldAcceptanceRate"))
    base_acceptance = _number(baseline.get("validFieldAcceptanceRate"))
    completion = _number(candidate.get("completionRate"))
    base_completion = _number(baseline.get("completionRate"))
    return bool(
        size in DIRECTION_CHUNK_CANDIDATES[1:]
        and isinstance(samples, int) and not isinstance(samples, bool) and samples >= 30
        and median is not None and base_median is not None and median <= base_median * 0.9
        and p95 is not None and base_p95 is not None and p95 <= base_p95
        and candidate.get("ownershipErrors") == 0
        and candidate.get("constraintViolations") == 0
        and completion is not None and base_completion is not None and completion >= base_completion
        and acceptance is not None and base_acceptance is not None
        and acceptance >= base_acceptance - 0.01
        and candidate.get("qualityNonDegraded") is True
    )


def validated_direction_chunk(provider: str, model: str, runtime: dict[str, Any] | None = None) -> int:
    """Read content-free local benchmark evidence; use the product default without matching evidence."""
    path = deps.DATA_ROOT / "llm-direction-benchmarks.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return 30
    entries = payload.get("profiles", []) if isinstance(payload, dict) else []
    expected = {"provider": provider, "model": model, **(runtime or {})}
    required = ("provider", "model", "modelFingerprint", "modelRevision", "omlxVersion", "machine", "macOS",
                "memoryGuard", "context", "promptProtocolVersion")
    profile = next((item for item in entries if isinstance(item, dict)
                    and all(item.get(key) == expected.get(key) for key in required)
                    and isinstance(item.get("fixtureHash"), str) and len(item["fixtureHash"]) == 64), None)
    results = profile.get("results", []) if isinstance(profile, dict) else []
    baseline = next((item for item in results if isinstance(item, dict) and item.get("chunkSize") == 10), None)
    if not isinstance(baseline, dict) or baseline.get("sampleCount", 0) < 30:
        return 30
    passing = [item for item in results if isinstance(item, dict) and direction_evidence_passes(item, baseline)]
    if not passing:
        return 30
    best = min(passing, key=lambda item: (_number(item.get("medianSeconds")) or float("inf"), item["chunkSize"]))
    return int(best["chunkSize"])


def direction_runtime_evidence(selected: dict[str, Any], context: int) -> dict[str, Any]:
    local = selected.get("localMetadata") if isinstance(selected.get("localMetadata"), dict) else {}
    settings = selected.get("settings") if isinstance(selected.get("settings"), dict) else {}
    return {"modelFingerprint": local.get("fingerprint"), "modelRevision": local.get("revision"),
            "omlxVersion": local.get("omlxVersion"), "machine": platform.machine(), "macOS": platform.mac_ver()[0],
            "memoryGuard": settings.get("memoryGuard"), "context": context,
            "promptProtocolVersion": deps.PROMPT_PROTOCOL_VERSION, "fixtureHash": None}


deps.register(
    __name__,
    ["DIRECTION_CHUNK_CANDIDATES", "direction_evidence_passes", "direction_runtime_evidence",
     "validated_direction_chunk"],
)

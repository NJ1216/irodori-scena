from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from tools.direction_benchmark_core import call_identity, production_score

_LOW_POWER_CACHE: tuple[float, bool] | None = None
_LOW_POWER_CACHE_SECONDS = 300.0


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        output.flush()
        os.fsync(output.fileno())


def completed_identities(path: Path) -> set[str]:
    if not path.exists():
        return set()
    result = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("status") == "completed" and isinstance(row.get("identity"), str):
            result.add(row["identity"])
    return result


def thermal_state(probe: Path) -> dict[str, Any]:
    try:
        result = json.loads(subprocess.check_output([str(probe)], text=True, timeout=5))
        result["lowPowerMode"] = current_low_power_mode()
        result["lowPowerModeSource"] = "pmset-active-profile"
        return result
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"state": "unknown", "lowPowerMode": None}


def parse_pmset_low_power(custom: str, power_source: str) -> bool | None:
    active = "AC Power" if "AC Power" in power_source else "Battery Power" if "Battery Power" in power_source else None
    if active is None:
        return None
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in custom.splitlines():
        line = raw.strip()
        if line.endswith(":"):
            current = line[:-1]
            sections[current] = []
        elif current:
            sections[current].append(line)
    for line in sections.get(active, []):
        parts = line.split()
        if len(parts) == 2 and parts[0] == "lowpowermode" and parts[1] in {"0", "1"}:
            return parts[1] == "1"
        if len(parts) == 2 and parts[0] == "powermode" and parts[1] in {"0", "1", "2"}:
            return parts[1] == "1"
    return None


def current_low_power_mode() -> bool | None:
    global _LOW_POWER_CACHE
    try:
        # Model loading can temporarily starve even tiny system commands.  A
        # longer timeout avoids mistaking scheduler delay for an unknown power
        # state while still failing closed if pmset genuinely stops responding.
        custom = subprocess.check_output(["pmset", "-g", "custom"], text=True, timeout=30)
        source = subprocess.check_output(["pmset", "-g", "ps"], text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        if _LOW_POWER_CACHE and time.monotonic() - _LOW_POWER_CACHE[0] <= _LOW_POWER_CACHE_SECONDS:
            return _LOW_POWER_CACHE[1]
        return None
    value = parse_pmset_low_power(custom, source)
    if value is not None:
        _LOW_POWER_CACHE = (time.monotonic(), value)
    return value


def require_clean_thermal(probe: Path) -> dict[str, Any]:
    state = thermal_state(probe)
    if state.get("lowPowerMode") is not True or state.get("state") != "nominal":
        raise RuntimeError(f"benchmark requires low power mode and nominal thermal state: {state}")
    return state


def wait_for_clean_thermal(
    probe: Path,
    *,
    poll_seconds: float = 60.0,
    stable_samples: int = 3,
    timeout_seconds: float | None = None,
    observe: Callable[[dict[str, Any]], None] | None = None,
    read_state: Callable[[Path], dict[str, Any]] = thermal_state,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Wait after an unhealthy observation until the machine is stably ready.

    An initially healthy machine starts immediately. Once waiting begins, several
    consecutive healthy samples are required so a brief nominal reading does not
    restart a long benchmark prematurely.
    """
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if stable_samples <= 0:
        raise ValueError("stable_samples must be positive")
    started = monotonic()
    waiting = False
    consecutive = 0
    while True:
        state = read_state(probe)
        healthy = state.get("lowPowerMode") is True and state.get("state") == "nominal"
        if healthy and not waiting:
            return state
        waiting = True
        consecutive = consecutive + 1 if healthy else 0
        observation = {
            "event": "thermal-wait-observation",
            "elapsedSeconds": monotonic() - started,
            "healthy": healthy,
            "consecutiveHealthySamples": consecutive,
            "requiredHealthySamples": stable_samples,
            "thermal": state,
        }
        if observe:
            observe(observation)
        if healthy and consecutive >= stable_samples:
            return state
        if timeout_seconds is not None and monotonic() - started >= timeout_seconds:
            raise TimeoutError(f"thermal recovery timed out: {state}")
        sleep(poll_seconds)


def rows_for(
    lines: list[dict[str, Any]], offset: int, size: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    source = lines[offset : offset + size]
    rows = [
        {**item, "alias": f"L{offset + index + 1}", "id": f"line-{offset + index + 1}"}
        for index, item in enumerate(source)
    ]

    def context(item: dict[str, Any]) -> dict[str, Any]:
        return {**item, "alias": "C", "id": "context"}

    return (
        rows,
        [context(item) for item in lines[max(0, offset - 3) : offset]],
        [context(item) for item in lines[offset + len(rows) : offset + len(rows) + 3]],
    )


def event_metrics(path: Path) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    if not path.exists():
        return metrics
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("event") != "prompt_metrics":
            continue
        delta = event.get("cacheDelta", {})
        metrics.update(delta if isinstance(delta, dict) else {})
    return metrics


def execute_call(
    *,
    deps: Any,
    request: Any,
    fixture: dict[str, Any],
    output: Path,
    probe: Path,
    suite: str,
    prompt_order: str,
    repetition: int,
    scenario: str,
    chunk_size: int,
    chunk_index: int,
    offset: int,
    cast_context: list[dict[str, Any]],
) -> dict[str, Any]:
    from server.modules.ai_direction import _request_text

    identity = call_identity(
        suite=suite,
        prompt_order=prompt_order,
        cast_count=fixture["castCount"],
        repetition=repetition,
        scenario=scenario,
        fixture_id=fixture["id"],
        chunk_size=chunk_size,
        chunk_index=chunk_index,
    )
    rows, before, after = rows_for(fixture["lines"], offset, chunk_size)
    raw_path = output / "raw" / f"{identity}.txt"
    before_thermal = require_clean_thermal(probe)
    deps.reset_local_llm_peak_memory()
    started = time.perf_counter()
    first_progress: list[float] = []
    raw = _request_text(
        request,
        rows,
        before,
        after,
        cast_context,
        job_id="direction-benchmark",
        debug_response_path=raw_path,
        on_progress=lambda _: first_progress.append(time.perf_counter()) if not first_progress else None,
        benchmark_prompt_order=prompt_order,
        benchmark_seed=42,
    )
    wall = time.perf_counter() - started
    atomic_write(raw_path, raw)
    after_thermal = thermal_state(probe)
    metrics = event_metrics(raw_path.with_suffix(".events.jsonl"))
    aliases = [str(row["alias"]) for row in rows]
    score = production_score(raw, aliases, rows, request, set(deps.AI_PROPOSABLE_EMOJIS))
    contaminated = after_thermal.get("state") != "nominal" or after_thermal.get("lowPowerMode") is not True
    return {
        "identity": identity,
        "suite": suite,
        "promptOrder": prompt_order,
        "castCount": fixture["castCount"],
        "repetition": repetition,
        "scenario": scenario,
        "fixtureId": fixture["id"],
        "fixtureSha256": fixture["sha256"],
        "chunkSize": chunk_size,
        "chunkIndex": chunk_index,
        "offset": offset,
        "status": "thermal-contaminated" if contaminated else "completed",
        "wallSeconds": wall,
        "ttftSeconds": first_progress[0] - started if first_progress else None,
        "metrics": metrics,
        "score": score,
        "thermalBefore": before_thermal,
        "thermalAfter": after_thermal,
    }

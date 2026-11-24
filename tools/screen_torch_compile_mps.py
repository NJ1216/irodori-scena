#!/usr/bin/env python3
"""Isolated, never-runtime-enabled torch.compile MPS screening harness."""

from __future__ import annotations
import argparse
import hashlib
import importlib
import json
import math
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


def parse_shapes(values: Sequence[str]) -> list[tuple[int, ...]]:
    shapes = []
    for value in values:
        try:
            shape = tuple(int(part) for part in value.lower().split("x"))
        except ValueError as error:
            raise ValueError(f"invalid shape: {value}") from error
        if not shape or any(dimension <= 0 for dimension in shape):
            raise ValueError(f"invalid shape: {value}")
        shapes.append(shape)
    return shapes


def run_child(command: Sequence[str], timeout_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        return {
            "status": "timeout",
            "wallClockSeconds": time.perf_counter() - started,
            "exitCode": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    record: dict[str, Any] = {
        "status": "completed" if process.returncode == 0 else "crashed",
        "wallClockSeconds": time.perf_counter() - started,
        "exitCode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
    if process.returncode == 0:
        try:
            record["result"] = json.loads(stdout)
        except json.JSONDecodeError:
            record["status"] = "invalid-output"
    return record


def _valid_time(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


def screening_passed(record: dict[str, Any]) -> bool:
    result, limits = record.get("result"), record.get("limits")
    if record.get("status") != "completed" or not isinstance(result, dict) or not isinstance(limits, dict):
        return False
    rows, unique, recompiles = result.get("rows"), result.get("uniqueGraphs"), result.get("recompiles")
    return bool(
        result.get("device") == "mps"
        and result.get("allExact") is True
        and result.get("knownShapesCompleted") is True
        and result.get("unknownShapesCompleted") is True
        and _valid_time(result.get("compileSeconds"))
        and result["compileSeconds"] <= limits["maxCompileSeconds"]
        and type(unique) is int
        and 1 <= unique <= limits["maxUniqueGraphs"]
        and type(recompiles) is int
        and 0 <= recompiles <= limits["maxRecompiles"]
        and isinstance(rows, list)
        and rows
        and all(_valid_time(row.get("eagerSeconds")) and _valid_time(row.get("compiledSeconds")) for row in rows)
    )


def _clone(torch: Any, value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().clone()
    if isinstance(value, tuple):
        return tuple(_clone(torch, item) for item in value)
    if isinstance(value, list):
        return [_clone(torch, item) for item in value]
    if isinstance(value, dict):
        return {key: _clone(torch, item) for key, item in value.items()}
    return value


def _tensor_hash(torch: Any, value: Any) -> str:
    digest = hashlib.sha256()
    values = value if isinstance(value, (tuple, list)) else (value,)
    for tensor in values:
        detached = tensor.detach().contiguous().to("cpu")
        digest.update(str(tuple(detached.shape)).encode())
        digest.update(str(detached.dtype).encode())
        digest.update(detached.numpy().tobytes())
    return digest.hexdigest()


def _exact(torch: Any, left: Any, right: Any) -> bool:
    lefts = left if isinstance(left, (tuple, list)) else (left,)
    rights = right if isinstance(right, (tuple, list)) else (right,)
    return len(lefts) == len(rights) and all(torch.equal(a, b) for a, b in zip(lefts, rights, strict=True))


def _memory(torch: Any) -> dict[str, int | None]:
    def read(name: str) -> int | None:
        function = getattr(torch.mps, name, None)
        return int(function()) if callable(function) else None

    return {
        "currentBytes": read("current_allocated_memory"),
        "driverBytes": read("driver_allocated_memory"),
        "recommendedMaxBytes": read("recommended_max_memory"),
    }


def _dynamo_counts(torch: Any) -> tuple[int | None, int | None]:
    utils = getattr(getattr(torch, "_dynamo", None), "utils", None)
    counters = getattr(utils, "counters", None)
    if not hasattr(counters, "get"):
        return None, None
    stats = counters.get("stats")
    if not hasattr(stats, "get") or type(stats.get("unique_graphs")) is not int:
        return None, None
    unique, recompiles = int(stats["unique_graphs"]), stats.get("recompiles")
    return unique, int(recompiles) if type(recompiles) is int else None


def worker(
    factory_name: str, known: Sequence[tuple[int, ...]], unknown: Sequence[tuple[int, ...]], dynamic: bool, seed: int
) -> int:
    import torch

    if not torch.backends.mps.is_available():
        raise RuntimeError("MPS is unavailable")
    repository = str(Path(__file__).resolve().parents[1])
    if repository not in sys.path:
        sys.path.insert(0, repository)
    module_name, separator, attribute = factory_name.partition(":")
    if not separator:
        raise ValueError("factory must use module:function syntax")
    torch.manual_seed(seed)
    factory = getattr(importlib.import_module(module_name), attribute)
    eager, make_args = factory(torch, torch.device("mps"))
    torch._dynamo.reset()
    compiled = torch.compile(eager, dynamic=dynamic)
    rows: list[dict[str, Any]] = []
    memories = [{"stage": "before", **_memory(torch)}]
    for kind, shape in [("known", item) for item in known] + [("unknown", item) for item in unknown]:
        source_args = make_args(shape)
        torch.mps.synchronize()
        started = time.perf_counter()
        expected = eager(*_clone(torch, source_args))
        torch.mps.synchronize()
        eager_seconds = time.perf_counter() - started
        memories.append({"stage": f"{kind}-eager", **_memory(torch)})
        torch.mps.synchronize()
        started = time.perf_counter()
        actual = compiled(*_clone(torch, source_args))
        torch.mps.synchronize()
        compiled_seconds = time.perf_counter() - started
        memories.append({"stage": f"{kind}-compiled", **_memory(torch)})
        rows.append(
            {
                "kind": kind,
                "shape": list(shape),
                "eagerSeconds": eager_seconds,
                "compiledSeconds": compiled_seconds,
                "exact": _exact(torch, expected, actual),
                "eagerSha256": _tensor_hash(torch, expected),
                "compiledSha256": _tensor_hash(torch, actual),
            }
        )
    unique, recompiles = _dynamo_counts(torch)
    currents = [item["currentBytes"] for item in memories if item["currentBytes"] is not None]
    print(
        json.dumps(
            {
                "device": "mps",
                "dynamic": dynamic,
                "seed": seed,
                "compileSeconds": rows[0]["compiledSeconds"],
                "uniqueGraphs": unique,
                "recompiles": recompiles,
                "knownShapesCompleted": sum(row["kind"] == "known" for row in rows) == len(known),
                "unknownShapesCompleted": sum(row["kind"] == "unknown" for row in rows) == len(unknown),
                "allExact": all(row["exact"] and row["eagerSha256"] == row["compiledSha256"] for row in rows),
                "rows": rows,
                "memorySamples": memories,
                "observedPeakCurrentBytes": max(currents, default=None),
                "torchVersion": torch.__version__,
            },
            ensure_ascii=False,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--factory", default="tools.torch_compile_probes:pointwise_probe")
    value.add_argument("--known-shape", action="append", required=True)
    value.add_argument("--unknown-shape", action="append", required=True)
    value.add_argument("--seed", type=int, default=19451217)
    value.add_argument("--timeout", type=float, default=300)
    value.add_argument("--max-compile-seconds", type=float, required=True)
    value.add_argument("--max-recompiles", type=int, required=True)
    value.add_argument("--max-unique-graphs", type=int, required=True)
    value.add_argument("--dynamic", action="store_true")
    value.add_argument("--output", type=Path, required=True)
    value.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    known, unknown = parse_shapes(args.known_shape), parse_shapes(args.unknown_shape)
    overlap = set(known).intersection(unknown)
    if overlap:
        formatted = ", ".join("x".join(str(value) for value in shape) for shape in sorted(overlap))
        raise ValueError(f"known and unknown shapes must be disjoint: {formatted}")
    limits = {
        "maxCompileSeconds": args.max_compile_seconds,
        "maxRecompiles": args.max_recompiles,
        "maxUniqueGraphs": args.max_unique_graphs,
    }
    if not _valid_time(args.timeout) or args.timeout == 0 or not _valid_time(args.max_compile_seconds):
        raise ValueError("invalid time threshold")
    if args.max_recompiles < 0 or args.max_unique_graphs < 1:
        raise ValueError("invalid graph threshold")
    if args.worker:
        return worker(args.factory, known, unknown, args.dynamic, args.seed)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        "--factory",
        args.factory,
        "--output",
        str(args.output),
        "--timeout",
        str(args.timeout),
        "--seed",
        str(args.seed),
        "--max-compile-seconds",
        str(args.max_compile_seconds),
        "--max-recompiles",
        str(args.max_recompiles),
        "--max-unique-graphs",
        str(args.max_unique_graphs),
    ]
    for shape in args.known_shape:
        command.extend(["--known-shape", shape])
    for shape in args.unknown_shape:
        command.extend(["--unknown-shape", shape])
    if args.dynamic:
        command.append("--dynamic")
    record = run_child(command, args.timeout)
    record.update(
        {
            "factory": args.factory,
            "seed": args.seed,
            "limits": limits,
            "knownShapes": [list(shape) for shape in known],
            "unknownShapes": [list(shape) for shape in unknown],
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if screening_passed(record) else 1


if __name__ == "__main__":
    raise SystemExit(main())

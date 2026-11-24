"""Per-machine CUDA acceleration calibration for routes no GPU allowlist covers.

The first generation of an unverified route runs upstream eager and the adapter
on the same request.  The adapter is enabled for that route only when the two
outputs are bit-identical; the eager result is what the user receives.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

PROMOTED = "promoted"
REJECTED = "rejected"
# A transient failure (out of memory) is not evidence about the route; it stays uncalibrated.
DEFERRED = "deferred"


def calibration_key(model_identity: str, variant_id: str, cuda_identity: tuple[str, str, str], engine_commit: str,
                    route: tuple[str, int, bool], request: Any = None) -> str:
    """Key every input that changes the adapter's sampler path, not only the route."""
    gpu, torch_version, cuda_version = cuda_identity
    schedule, steps, reference = route
    caption = "caption" if str(getattr(request, "caption", "") or "").strip() else "no-caption"
    candidates = f"candidates-{int(getattr(request, 'num_candidates', 1) or 1)}"
    return "|".join((engine_commit, model_identity, variant_id, gpu, torch_version, cuda_version,
                     schedule, str(steps), "reference" if reference else "no-reference", caption, candidates))


class CalibrationStore:
    """JSON outcomes keyed by route; an unreadable file is treated as empty."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _routes(self) -> dict[str, Any]:
        """Missing or corrupt files are empty; any other read failure raises so no record is lost."""
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {}
        routes = payload.get("routes") if isinstance(payload, dict) else None
        return routes if isinstance(routes, dict) else {}

    def status(self, key: str) -> str | None:
        try:
            entry = self._routes().get(key)
        except OSError:
            return None
        status = entry.get("status") if isinstance(entry, dict) else None
        return status if status in (PROMOTED, REJECTED) else None

    def record(self, key: str, status: str, **details: Any) -> None:
        routes = self._routes()
        routes[key] = {"status": status, "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **details}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".calibration-", suffix=".json")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump({"version": 1, "routes": routes}, handle, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def same_audio(first: Any, second: Any) -> bool:
    if getattr(first, "sample_rate", None) != getattr(second, "sample_rate", None):
        return False
    left = getattr(first, "audios", None) or [getattr(first, "audio", None)]
    right = getattr(second, "audios", None) or [getattr(second, "audio", None)]
    return len(left) == len(right) and all(_same_tensor(a, b) for a, b in zip(left, right))


def _same_tensor(left: Any, right: Any) -> bool:
    try:
        import torch

        if isinstance(left, torch.Tensor) and isinstance(right, torch.Tensor):
            return left.shape == right.shape and bool(torch.equal(left.cpu(), right.cpu()))
    except ImportError:
        pass
    return left == right


def calibrate(eager: Callable[[], Any], optimized: Callable[[], Any]) -> tuple[Any, dict[str, Any]]:
    """Return the eager result and the outcome; adapter failures reject instead of raising."""
    started = time.perf_counter()
    result = eager()
    eager_seconds = time.perf_counter() - started
    outcome: dict[str, Any] = {"eager_seconds": round(eager_seconds, 4)}
    started = time.perf_counter()
    try:
        candidate = optimized()
    except Exception as error:  # noqa: BLE001 - any adapter failure only disqualifies the route.
        transient = "out of memory" in str(error).lower() or type(error).__name__ == "OutOfMemoryError"
        outcome.update(status=DEFERRED if transient else REJECTED, detail=f"{type(error).__name__}: {error}"[-300:])
        return result, outcome
    outcome["adapter_seconds"] = round(time.perf_counter() - started, 4)
    outcome["status"] = PROMOTED if same_audio(result, candidate) else REJECTED
    return result, outcome

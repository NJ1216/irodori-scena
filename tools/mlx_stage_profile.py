"""Stage breakdown for one MLX generate call (benchmark-only instrumentation).

MLX is lazy, so each wrapped stage forces evaluation of its outputs before the
clock stops. This adds synchronisation, so profiled runs are reported apart
from the alternating A/B timings and never mixed into them.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator


def _evaluate(value: Any) -> None:
    import mlx.core as mx

    leaves = [item for item in (value if isinstance(value, (tuple, list)) else (value,)) if item is not None]
    arrays = [item for item in leaves if isinstance(item, mx.array)]
    if arrays:
        mx.eval(*arrays)


@contextmanager
def _patched(owner: Any, name: str, replacement: Callable[..., Any]) -> Iterator[None]:
    had_own = name in vars(owner)
    original = vars(owner).get(name)
    setattr(owner, name, replacement)
    try:
        yield
    finally:
        if had_own:
            setattr(owner, name, original)
        else:
            delattr(owner, name)


def profile_once(model: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    timings: dict[str, float] = {}
    calls: dict[str, int] = {}

    def wrap(stage: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def timed(*args: Any, **inner: Any) -> Any:
            started = time.perf_counter()
            value = function(*args, **inner)
            _evaluate(value)
            timings[stage] = round(timings.get(stage, 0.0) + (time.perf_counter() - started) * 1000, 3)
            calls[stage] = calls.get(stage, 0) + 1
            return value
        return timed

    sampling_module = sys.modules[type(model).__module__]
    started = time.perf_counter()
    with _patched(model, "_encode_ref_audios", wrap("referenceEncode", model._encode_ref_audios)), \
            _patched(model.model, "encode_conditions_full", wrap("conditionEncode", model.model.encode_conditions_full)), \
            _patched(model.model, "predict_duration_log_frames", wrap("duration", model.model.predict_duration_log_frames)), \
            _patched(sampling_module, "sample_euler_cfg", wrap("sampling", sampling_module.sample_euler_cfg)), \
            _patched(model.dacvae, "decode", wrap("decode", model.dacvae.decode)):
        next(iter(model.generate(**kwargs)))
    timings["total"] = round((time.perf_counter() - started) * 1000, 3)
    return {"stageMs": timings, "calls": calls}

"""SCENA-owned compatibility boundary for optional Irodori-TTS acceleration.

This module deliberately depends only on public runtime objects.  Unknown engine
revisions and API shapes are never guessed: they keep using upstream synthesize.
"""

from __future__ import annotations

import inspect
import os
import sys
import time
from collections import OrderedDict
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from irodori_cuda_calibration import CalibrationStore, calibrate, calibration_key
    from irodori_cuda_graphs import step_graphs, use_step_graphs
except ImportError:
    from server.irodori_cuda_calibration import CalibrationStore, calibrate, calibration_key
    from server.irodori_cuda_graphs import step_graphs, use_step_graphs

VERIFIED_ENGINES = {"8224dafb46d0aba89209a8f905f1cb7e3299d9c1"}
VERIFIED_MODELS = {
    "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b",
    "Aratako/Irodori-TTS-v4-Small@4c92c7ee2bb15c19a97cf4e86d24fd6bf33b0135",
}
_CUDA_V41 = "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
_CUDA_4070_TI = ("NVIDIA GeForce RTX 4070 Ti", "2.10.0+cu128", "12.8")
VERIFIED_CUDA_ROUTES: set[tuple[str, str, str, str, str, int, bool]] = {
    (_CUDA_V41, *_CUDA_4070_TI, schedule, steps, reference)
    for schedule, steps in (("sway", 8), ("sway", 16), ("linear", 40))
    for reference in (False, True)
}
# Quantized checkpoints share one identity per distribution; the variant decides eligibility.
CUDA_QUANTIZED_MODELS = {
    "Aratako/Irodori-TTS-v4.1-Small-Quantized@ef04e6c3ba56138ae23e86a2eabc004f76990e37",
    "Aratako/Irodori-TTS-v4-Small-Quantized@4a5a4d68c5a73d2742fbdb0ce679522f8c7fbdab",
}
# FP8 weight-only fails inside the adapter; W8A8 and FP8 Dynamic are never recommended.
CUDA_CALIBRATION_VARIANTS = {"pytorch-fp32", "pytorch-w8a16", "pytorch-w4a16"}
CALIBRATE_PROFILE = "cuda-calibration"
MPS_PROFILE = "scena-mps-v1"
CUDA_PROFILE = "scena-cuda-graph-v3"
# Kept for callers/tests written before the adapter gained CUDA support.
PROFILE = MPS_PROFILE
EAGER_PROFILE = "upstream-eager"
MEANFLOW_PROFILE = "upstream-meanflow"
MEANFLOW_ENGINE = "89f9d8fbd4d51ea019867ee1197725ede1df13c5"
MEANFLOW_MODEL = "Aratako/Irodori-TTS-v4.1-Small-MF@ccc78f5d480b6e51b69b2d5042a14c4da04fea6e"
_CACHES: dict[int, TensorLru] = {}


def cache_budget(total_memory: int | None) -> int:
    if not isinstance(total_memory, int) or total_memory <= 0:
        return 0
    return min(total_memory // 400, 128 * 1024**2)


def cuda_cache_budget(torch: Any, device: Any) -> int:
    """Bound persistent tensors by currently free VRAM, never host RAM."""
    try:
        free, _total = torch.cuda.mem_get_info(device)
        return min(max(0, int(free)) // 16, 128 * 1024**2)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0


def reference_identity(path: str | None) -> tuple[str, int, int] | None:
    if not path:
        return None
    resolved = Path(path).resolve()
    stat = resolved.stat()
    return str(resolved), stat.st_size, stat.st_mtime_ns


class TensorLru:
    """Byte-bounded worker-local cache; values are never serialized to disk."""

    def __init__(self, limit: int) -> None:
        self.limit = max(0, limit)
        self.bytes = 0
        self._items: OrderedDict[tuple[Any, ...], tuple[Any, int]] = OrderedDict()

    def get(self, key: tuple[Any, ...]) -> Any | None:
        item = self._items.pop(key, None)
        if item is None:
            return None
        self._items[key] = item
        return item[0]

    def put(self, key: tuple[Any, ...], value: Any, size: int) -> None:
        if self.limit == 0 or size <= 0 or size > self.limit:
            return
        previous = self._items.pop(key, None)
        if previous:
            self.bytes -= previous[1]
        self._items[key] = (value, size)
        self.bytes += size
        while self.bytes > self.limit:
            _key, (_value, removed) = self._items.popitem(last=False)
            self.bytes -= removed

    def clear(self) -> None:
        self._items.clear()
        self.bytes = 0


@dataclass(frozen=True)
class Decision:
    profile: str
    fallback_reason: str | None
    precision: str = "fp32"
    route: str = "unknown"
    calibration_key: str | None = None
    step_graphs: bool = False


def _route(request: Any | None) -> tuple[str, int, bool]:
    schedule = str(getattr(request, "t_schedule_mode", "unknown")).strip().lower()
    steps = int(getattr(request, "num_steps", 0) or 0)
    reference = not bool(getattr(request, "no_ref", True))
    return schedule, steps, reference


def _route_label(route: tuple[str, int, bool]) -> str:
    return f"{route[0]}-{route[1]}-{'reference' if route[2] else 'no-reference'}"


def _cuda_runtime_identity(runtime: Any) -> tuple[str, str, str] | None:
    try:
        import torch
        gpu = str(torch.cuda.get_device_name(runtime.model_device))
        return gpu, str(torch.__version__), str(torch.version.cuda)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return None


def _cuda_gate(runtime: Any, engine_commit: str, model_identity: str, route: tuple[str, int, bool],
               variant_id: str, calibration: CalibrationStore | None, request: Any) -> tuple[str | None, str | None]:
    """Return (fallback reason, calibration key still pending) for a CUDA runtime."""
    cuda_identity = _cuda_runtime_identity(runtime)
    if cuda_identity is None:
        return "cuda-runtime-unknown", None
    if variant_id not in CUDA_CALIBRATION_VARIANTS:
        return "cuda-variant-unsupported", None
    if variant_id == "pytorch-fp32" and (model_identity, *cuda_identity, *route) in VERIFIED_CUDA_ROUTES:
        return None, None
    if calibration is None:
        return "cuda-route-not-promoted", None
    key = calibration_key(model_identity, variant_id, cuda_identity, f"{engine_commit}|{CUDA_PROFILE}", route, request)
    status = calibration.status(key)
    if status == "rejected":
        return "cuda-calibration-rejected", None
    return None, (None if status == "promoted" else key)


def select_profile(runtime: Any, engine_commit: str | None, model_identity: str | None,
                   request: Any | None = None, *, variant_id: str = "pytorch-fp32",
                   calibration: CalibrationStore | None = None) -> Decision:
    route = _route(request)
    route_label = _route_label(route)
    if engine_commit == MEANFLOW_ENGINE and model_identity == MEANFLOW_MODEL:
        parameterization = str(getattr(getattr(runtime, "model_cfg", None), "flow_parameterization", ""))
        if parameterization != "meanflow":
            return Decision(EAGER_PROFILE, "meanflow-parameterization-mismatch", route=route_label)
        return Decision(MEANFLOW_PROFILE, None, route=route_label)
    if engine_commit not in VERIFIED_ENGINES:
        return Decision(EAGER_PROFILE, "unverified-engine", route=route_label)
    key = getattr(runtime, "key", None)
    device = str(getattr(runtime, "model_device", ""))
    if model_identity not in VERIFIED_MODELS and not (device.startswith("cuda") and model_identity in CUDA_QUANTIZED_MODELS):
        return Decision(EAGER_PROFILE, "unverified-model", route=route_label)
    pending_key = None
    if device not in ("mps", "cuda") and not device.startswith("cuda:"):
        return Decision(EAGER_PROFILE, "unsupported-device", route=route_label)
    if device.startswith("cuda"):
        reason, pending_key = _cuda_gate(runtime, str(engine_commit), str(model_identity), route, variant_id, calibration, request)
        if reason:
            return Decision(EAGER_PROFILE, reason, route=route_label)
    if not bool(getattr(key, "codec_deterministic_encode", False)):
        return Decision(EAGER_PROFILE, "nondeterministic-codec", route=route_label)
    synthesize = getattr(runtime, "synthesize", None)
    try:
        parameters = inspect.signature(synthesize).parameters
    except (TypeError, ValueError):
        return Decision(EAGER_PROFILE, "api-shape-mismatch", route=route_label)
    required_runtime = ("_load_reference_latent", "synthesize")
    required_model = ("encode_conditions", "forward_with_encoded_conditions", "build_context_kv_cache")
    if "req" not in parameters or not all(hasattr(runtime, name) for name in required_runtime):
        return Decision(EAGER_PROFILE, "api-shape-mismatch", route=route_label)
    if not all(hasattr(runtime.model, name) for name in required_model):
        return Decision(EAGER_PROFILE, "api-shape-mismatch", route=route_label)
    graphs = device.startswith("cuda") and use_step_graphs(variant_id, route[1])
    if pending_key is not None:
        return Decision(CALIBRATE_PROFILE, None, route=route_label, calibration_key=pending_key, step_graphs=graphs)
    return Decision(MPS_PROFILE if device == "mps" else CUDA_PROFILE, None, route=route_label, step_graphs=graphs)


def _cache_limit(runtime: Any) -> int:
    if str(getattr(runtime, "model_device", "")).startswith("cuda"):
        try:
            import torch

            return cuda_cache_budget(torch, runtime.model_device)
        except ImportError:
            return 0
    return cache_budget(physical_memory())


def _tensor_bytes(value: Any) -> int:
    if isinstance(value, (tuple, list)):
        return sum(_tensor_bytes(item) for item in value)
    element_size = getattr(value, "element_size", None)
    elements = getattr(value, "numel", None)
    if not callable(element_size) or not callable(elements):
        return 0
    return int(element_size() * elements())


def _normalized(value: Any) -> str:
    from irodori_tts.text_normalization import normalize_text

    return normalize_text(str(value or "")).strip()


def _identity(runtime: Any, request: Any, engine_commit: str) -> tuple[Any, ...]:
    key = runtime.key
    ref = reference_identity(getattr(request, "ref_wav", None))
    return (
        engine_commit,
        str(getattr(key, "checkpoint", "")),
        str(getattr(key, "codec_repo", "")),
        str(runtime.model_device),
        str(getattr(runtime, "_model_dtype", "")),
        _normalized(getattr(request, "text", "")),
        _normalized(getattr(request, "caption", "")),
        int(getattr(request, "num_candidates", 1)),
        bool(getattr(request, "no_ref", False)),
        str(getattr(request, "speaker_uncond_mode", "mask")),
        getattr(request, "ref_normalize_db", None),
        bool(getattr(request, "ref_ensure_max", False)),
        getattr(request, "max_ref_seconds", None),
        getattr(request, "max_text_len", None),
        getattr(request, "max_caption_len", None),
        ref,
    )


@contextmanager
def _optimized_calls(runtime: Any, request: Any, engine_commit: str, stats: dict[str, Any], graphs: bool = False):
    try:
        from irodori_acceleration_sampler import sample_euler_rf_cfg
    except ImportError:
        from server.irodori_acceleration_sampler import sample_euler_rf_cfg

    cache = _CACHES.setdefault(id(runtime), TensorLru(_cache_limit(runtime)))
    base_key = _identity(runtime, request, engine_commit)
    original_reference = runtime._load_reference_latent
    original_encode = runtime.model.encode_conditions
    original_kv = runtime.model.build_context_kv_cache
    original_forward = runtime.model.forward_with_encoded_conditions
    runtime_module = sys.modules[runtime.__class__.__module__]
    original_sampler = runtime_module.sample_euler_rf_cfg
    encoded_this_request: Any | None = None
    replay: Any = original_forward

    def load_reference(*, req: Any, batch_size: int, messages: list[str]) -> Any:
        key = ("reference",) + base_key[0:5] + (base_key[7],) + base_key[8:]
        cached = cache.get(key)
        if cached is not None:
            stats["referenceCache"] = "hit"
            return cached
        started = time.perf_counter()
        value = original_reference(req=req, batch_size=batch_size, messages=messages)
        stats["referencePrepareMs"] = round((time.perf_counter() - started) * 1000, 3)
        cache.put(key, value, _tensor_bytes(value))
        stats["referenceCache"] = "miss"
        return value

    def encode_conditions(**kwargs: Any) -> Any:
        nonlocal encoded_this_request
        key = ("conditions",) + base_key
        if encoded_this_request is not None:
            stats["conditionShared"] = True
            return encoded_this_request
        cached = cache.get(key)
        if cached is not None:
            stats["conditionCache"] = "hit"
            encoded_this_request = cached
            return cached
        value = original_encode(**kwargs)
        cache.put(key, value, _tensor_bytes(value))
        stats["conditionCache"] = "miss"
        encoded_this_request = value
        return value

    def build_context_kv_cache(**kwargs: Any) -> Any:
        started = time.perf_counter()
        value = original_kv(**kwargs)
        stats["contextKvMs"] = round(stats.get("contextKvMs", 0.0) + (time.perf_counter() - started) * 1000, 3)
        return value

    def forward_with_encoded_conditions(**kwargs: Any) -> Any:
        started = time.perf_counter()
        value = replay(**kwargs)
        stats["rfForwardMs"] = round(stats.get("rfForwardMs", 0.0) + (time.perf_counter() - started) * 1000, 3)
        return value

    runtime._load_reference_latent = load_reference
    runtime.model.encode_conditions = encode_conditions
    runtime.model.build_context_kv_cache = build_context_kv_cache
    runtime.model.forward_with_encoded_conditions = forward_with_encoded_conditions
    runtime_module.sample_euler_rf_cfg = sample_euler_rf_cfg
    try:
        with ExitStack() as stack:
            if graphs:
                import torch

                replay = stack.enter_context(step_graphs(torch, runtime.model, original_forward))
                stats["cudaGraphs"] = True
            yield cache
    finally:
        runtime._load_reference_latent = original_reference
        runtime.model.encode_conditions = original_encode
        runtime.model.build_context_kv_cache = original_kv
        runtime.model.forward_with_encoded_conditions = original_forward
        runtime_module.sample_euler_rf_cfg = original_sampler


def run(
    runtime: Any,
    request: Any,
    *,
    engine_commit: str | None,
    model_identity: str | None,
    prepare: bool = False,
    variant_id: str = "pytorch-fp32",
    calibration: CalibrationStore | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Execute through the verified boundary and report the path actually used.

    The verified engine already exposes condition encoding and context-KV reuse.
    SCENA owns selection, cache lifetime, measurements, and fallback semantics.
    """
    decision = select_profile(runtime, engine_commit, model_identity, request, variant_id=variant_id, calibration=calibration)
    started = time.perf_counter()
    optimization_stats: dict[str, Any] = {"device": str(getattr(runtime, "model_device", ""))}
    _reset_cuda_peak(runtime, optimization_stats["device"])
    try:
        if decision.profile in {EAGER_PROFILE, MEANFLOW_PROFILE}:
            result = runtime.synthesize(request, log_fn=None)
        elif decision.profile == CALIBRATE_PROFILE and not getattr(request, "lora_adapter", None):
            result, decision = _calibrate_route(runtime, request, str(engine_commit), decision, calibration, optimization_stats)
        else:
            if getattr(request, "lora_adapter", None):
                decision = Decision(EAGER_PROFILE, "dynamic-lora", route=decision.route)
                result = runtime.synthesize(request, log_fn=None)
            else:
                with _optimized_calls(runtime, request, str(engine_commit), optimization_stats, decision.step_graphs) as cache:
                    try:
                        result = runtime.synthesize(request, log_fn=None)
                    finally:
                        if prepare:
                            cache.clear()
    except Exception as error:
        # No retry is useful when the selected path is already upstream eager.
        if decision.profile in {EAGER_PROFILE, MEANFLOW_PROFILE, CALIBRATE_PROFILE}:
            raise
        cached = _CACHES.get(id(runtime))
        if cached is not None:
            cached.clear()
        out_of_memory = type(error).__name__ == "OutOfMemoryError"
        optimization_stats["fallbackDetail"] = f"{type(error).__name__}: {error}"[-500:]
        result = None
    if result is None:
        # Retry outside the handler: the traceback would otherwise keep a half-recorded
        # CUDA Graph (and its memory pool) alive during the eager attempt.
        if decision.profile == CUDA_PROFILE and out_of_memory:
            try:
                import torch

                torch.cuda.empty_cache()
                optimization_stats["cudaCacheCleared"] = True
            except (ImportError, AttributeError, RuntimeError):
                pass
        result = runtime.synthesize(request, log_fn=None)
        decision = Decision(EAGER_PROFILE, "optimized-path-failed", route=decision.route)
    timings = {name: round(seconds * 1000, 3) for name, seconds in result.stage_timings}
    for name in ("referencePrepareMs", "contextKvMs", "rfForwardMs"):
        if name in optimization_stats:
            timings[name.removesuffix("Ms")] = optimization_stats[name]
    timings["workerTotal"] = round((time.perf_counter() - started) * 1000, 3)
    peak_vram = _cuda_peak(runtime, optimization_stats["device"])
    return result, {
        "optimizationProfile": decision.profile,
        "precision": decision.precision,
        "route": decision.route,
        "fallbackReason": decision.fallback_reason,
        "stageTimingsMs": timings,
        "optimizationStats": optimization_stats,
        "peakVramBytes": peak_vram,
    }


def calibration_needed(runtime: Any, request: Any, *, engine_commit: str | None, model_identity: str | None,
                       variant_id: str, calibration: CalibrationStore | None) -> bool:
    """True when this route has no recorded calibration outcome and would calibrate now."""
    decision = select_profile(runtime, engine_commit, model_identity, request, variant_id=variant_id, calibration=calibration)
    return decision.profile == CALIBRATE_PROFILE


def _calibrate_route(runtime: Any, request: Any, engine_commit: str, decision: Decision,
                     calibration: CalibrationStore | None, stats: dict[str, Any]) -> tuple[Any, Decision]:
    def optimized() -> Any:
        with _optimized_calls(runtime, request, engine_commit, stats, decision.step_graphs) as cache:
            try:
                return runtime.synthesize(request, log_fn=None)
            finally:
                cache.clear()

    result, outcome = calibrate(lambda: runtime.synthesize(request, log_fn=None), optimized)
    if outcome["status"] != "promoted":
        cached = _CACHES.get(id(runtime))
        if cached is not None:
            cached.clear()
    if calibration is not None and decision.calibration_key and outcome["status"] != "deferred":
        try:
            calibration.record(decision.calibration_key, **outcome)
        except OSError as error:
            # The audio exists; an unsaved outcome only means this route calibrates again.
            outcome["recordError"] = f"{type(error).__name__}: {error}"[-200:]
    stats["calibration"] = outcome
    return result, Decision(EAGER_PROFILE, f"cuda-calibration-{outcome['status']}", route=decision.route)


def physical_memory() -> int | None:
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, OSError, TypeError, ValueError):
        return None


def clear_worker_caches() -> None:
    for cache in _CACHES.values():
        cache.clear()
    _CACHES.clear()


def _reset_cuda_peak(runtime: Any, device: str) -> None:
    if not device.startswith("cuda"):
        return
    try:
        import torch
        torch.cuda.reset_peak_memory_stats(runtime.model_device)
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        pass


def _cuda_peak(runtime: Any, device: str) -> int | None:
    if not device.startswith("cuda"):
        return None
    try:
        import torch
        return int(torch.cuda.max_memory_allocated(runtime.model_device))
    except (ImportError, AttributeError, RuntimeError, TypeError, ValueError):
        return None

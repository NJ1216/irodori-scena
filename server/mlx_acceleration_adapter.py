"""SCENA-owned acceleration boundary around the pinned mlx-audio Irodori runtime.

The adapter never edits mlx-audio. Each feature temporarily replaces methods on
the loaded model for one generate call and restores them afterwards. Gating is
by runtime engine id and API shape, not by model revision, so updated model
revisions keep working; an unknown runtime or missing method uses the plain
generate path and reports why.
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import ExitStack, contextmanager
from typing import Any, Callable, ContextManager, Iterator

from server.irodori_acceleration_adapter import Decision, TensorLru, cache_budget, physical_memory, reference_identity
from server.mlx_decode_compile import clear as clear_compiled_decode
from server.mlx_decode_compile import compile_decode

PROFILE = "scena-mlx-v1"
EAGER_PROFILE = "upstream-mlx"
# The external MLX environment can import only top-level server/*.py sources
# (server.modules lives inside the frozen API bundle), so the pinned runtime
# ids are repeated here; a test keeps them equal to tts_mlx_variants.MLX_RUNTIMES.
SUPPORTED_RUNTIMES = frozenset({"mlx-audio@0.5.0", "mlx-audio@de43d7c381e1f8fa108ac44bca707d9e613f7355"})
REQUIRED_API = (
    ("", "generate"),
    ("", "_encode_ref_audios"),
    ("model", "encode_conditions_full"),
    ("model", "build_kv_cache"),
    ("model", "forward_with_conditions"),
    ("dacvae", "decode"),
)

# name -> factory(model, kwargs, context) returning a context manager that
# installs the feature for one call. Later tasks register their features here.
Feature = Callable[[Any, dict[str, Any], dict[str, Any]], ContextManager[Any]]
FEATURES: dict[str, Feature] = {}
# Adopted features (each measured PCM-identical to the unaccelerated path).
DEFAULT_FEATURES: frozenset[str] = frozenset({"reference-cache", "condition-share", "compile", "compile-decode"})
_CACHE_CLEARERS: list[Callable[[], None]] = []
# After an optimized call fails once, this worker stops optimizing so a broken
# feature never doubles the cost of every later generation.
_FAILURE: dict[str, str] = {}


def reset_failures() -> None:
    _FAILURE.clear()


def select_profile(model: Any, runtime_version: str | None, *, lora: bool) -> Decision:
    if lora:
        return Decision(EAGER_PROFILE, "dynamic-lora")
    if runtime_version not in SUPPORTED_RUNTIMES:
        return Decision(EAGER_PROFILE, "unverified-runtime")
    if _FAILURE:
        return Decision(EAGER_PROFILE, "disabled-after-failure")
    for owner_name, method in REQUIRED_API:
        owner = getattr(model, owner_name, None) if owner_name else model
        if not callable(getattr(owner, method, None)):
            return Decision(EAGER_PROFILE, "api-shape-mismatch")
    return Decision(PROFILE, None)


def clear_caches() -> None:
    for clear in _CACHE_CLEARERS:
        clear()


@contextmanager
def _patched(owner: Any, name: str, replacement: Callable[..., Any]) -> Iterator[None]:
    """Shadow a method on one instance and always remove the shadow afterwards."""
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


def _array_bytes(value: Any) -> int:
    if isinstance(value, (tuple, list)):
        return sum(_array_bytes(item) for item in value)
    return int(getattr(value, "nbytes", 0) or 0)


# Worker-local, byte-bounded and never written to disk (same budget as the MPS adapter).
_REFERENCES = TensorLru(cache_budget(physical_memory()))
_CACHE_CLEARERS.append(_REFERENCES.clear)


@contextmanager
def _reference_cache(model: Any, kwargs: dict[str, Any], context: dict[str, Any]) -> Iterator[None]:
    reference = kwargs.get("ref_audio")
    if reference is None:
        yield
        return
    references = reference if isinstance(reference, (list, tuple)) else [reference]
    if not all(isinstance(item, (str, os.PathLike)) for item in references):
        context["cacheStats"]["referenceCache"] = "uncacheable"
        yield
        return
    key = ("reference", id(model), tuple(reference_identity(os.fspath(item)) for item in references), kwargs.get("max_ref_seconds"))
    cached = _REFERENCES.get(key)
    if cached is not None:
        context["cacheStats"]["referenceCache"] = "hit"
        with _patched(model, "_load_ref_waveform", lambda _reference: None), \
                _patched(model, "_encode_ref_audios", lambda _audios, max_ref_seconds=None: cached):
            yield
        return
    original = model._encode_ref_audios

    def encode(audios: Any, max_ref_seconds: Any = None) -> Any:
        started = time.perf_counter()
        value = original(audios, max_ref_seconds=max_ref_seconds)
        _REFERENCES.put(key, value, _array_bytes(value))
        context["stageTimingsMs"]["referenceEncode"] = round((time.perf_counter() - started) * 1000, 3)
        return value

    context["cacheStats"]["referenceCache"] = "miss"
    with _patched(model, "_encode_ref_audios", encode):
        yield


FEATURES["reference-cache"] = _reference_cache

_CONDITIONS = TensorLru(cache_budget(physical_memory()))
_CACHE_CLEARERS.append(_CONDITIONS.clear)
# The context KV of one line is 47-94 MB (v4.1 Small), as large as the whole
# condition budget on 16-32 GB Macs. Keep only the latest line's KV, outside
# that budget, so retakes of the current line always reuse it and the small
# conditions of earlier lines are never evicted by it.
_LATEST_KV: dict[tuple[Any, ...], Any] = {}
_CACHE_CLEARERS.append(_LATEST_KV.clear)


def _content_key(value: Any) -> tuple[Any, ...] | None:
    """Hash the inputs' contents (token ids, masks, latents are small)."""
    if value is None:
        return None
    import numpy as np

    if "bfloat16" in str(getattr(value, "dtype", "")):  # numpy has no bfloat16
        import mlx.core as mx

        value = value.astype(mx.float32)
    data = np.asarray(value)
    return (tuple(data.shape), str(data.dtype), hashlib.sha1(data.tobytes()).hexdigest())


@contextmanager
def _condition_share(model: Any, kwargs: dict[str, Any], context: dict[str, Any]) -> Iterator[None]:
    """Encode conditions once per call and reuse them (and their context KV) on retakes."""
    inner = model.model
    original_encode, original_kv = inner.encode_conditions_full, inner.build_kv_cache
    current: dict[str, Any] = {}
    stats = context["cacheStats"]

    def encode(text_input_ids: Any, text_mask: Any, ref_latent: Any = None, ref_mask: Any = None,
               caption_input_ids: Any = None, caption_mask: Any = None) -> Any:
        inputs = (text_input_ids, text_mask, ref_latent, ref_mask, caption_input_ids, caption_mask)
        if "inputs" in current and all(a is b for a, b in zip(inputs, current["inputs"], strict=True)):
            stats["conditionShared"] = True
            return current["value"]
        key = ("conditions", id(model), *(_content_key(item) for item in inputs))
        value = _CONDITIONS.get(key)
        stats["conditionCache"] = "miss" if value is None else "hit"
        if value is None:
            value = original_encode(text_input_ids, text_mask, ref_latent=ref_latent, ref_mask=ref_mask,
                                    caption_input_ids=caption_input_ids, caption_mask=caption_mask)
            _CONDITIONS.put(key, value, _array_bytes(value))
        current.update(inputs=inputs, key=key, value=value)
        return value

    def build_kv(text_state: Any, speaker_state: Any = None, caption_state: Any = None) -> Any:
        shared = current.get("value")
        if shared is None or not (text_state is shared[0] and speaker_state is shared[2] and caption_state is shared[4]):
            return original_kv(text_state, speaker_state, caption_state)
        key = current["key"]
        value = _LATEST_KV.get(key)
        stats["kvCache"] = "miss" if value is None else "hit"
        if value is None:
            value = original_kv(text_state, speaker_state, caption_state)
            _LATEST_KV.clear()
            _LATEST_KV[key] = value
        return value

    with _patched(inner, "encode_conditions_full", encode), _patched(inner, "build_kv_cache", build_kv):
        yield


FEATURES["condition-share"] = _condition_share


def _mx_compile(function: Callable[..., Any]) -> Callable[..., Any]:
    import mlx.core as mx

    return mx.compile(function)


# One compiled DiT forward per loaded model; MLX traces again for each new
# input shape (sequence length) and keeps those traces inside the function.
_COMPILED: dict[int, Callable[..., Any]] = {}
_CACHE_CLEARERS.append(_COMPILED.clear)


@contextmanager
def _compile_forward(model: Any, kwargs: dict[str, Any], context: dict[str, Any]) -> Iterator[None]:
    inner = model.model
    compiled = _COMPILED.get(id(model))
    if compiled is None:
        compiled = _COMPILED[id(model)] = _mx_compile(inner.forward_with_conditions)
    with _patched(inner, "forward_with_conditions", lambda *args, **inputs: compiled(*args, **inputs)):
        yield


FEATURES["compile"] = _compile_forward
FEATURES["compile-decode"] = lambda model, kwargs, context: compile_decode(model, kwargs, context, patched=_patched)
_CACHE_CLEARERS.append(clear_compiled_decode)


def _plain(model: Any, kwargs: dict[str, Any]) -> Any:
    return next(iter(model.generate(**kwargs)))


def run(model: Any, kwargs: dict[str, Any], *, runtime_version: str | None,
        features: frozenset[str], lora: bool) -> tuple[Any, dict[str, Any]]:
    unknown = sorted(set(features) - set(FEATURES))
    if unknown:
        raise ValueError(f"Unknown MLX acceleration feature: {', '.join(unknown)}")
    decision = select_profile(model, runtime_version, lora=lora)
    enabled = sorted(features) if decision.profile == PROFILE else []
    context: dict[str, Any] = {"stageTimingsMs": {}, "cacheStats": {}}
    started = time.perf_counter()
    report: dict[str, Any] = {}
    if not enabled:
        result = _plain(model, kwargs)
    else:
        try:
            with ExitStack() as stack:
                for name in enabled:
                    stack.enter_context(FEATURES[name](model, kwargs, context))
                result = _plain(model, kwargs)
        except Exception as error:  # noqa: BLE001 - any optimized failure gets one plain attempt
            clear_caches()
            _FAILURE["detail"] = f"{type(error).__name__}: {error}"[-500:]
            result = _plain(model, kwargs)
            decision = Decision(EAGER_PROFILE, "optimized-path-failed")
            report["fallbackDetail"] = f"{type(error).__name__}: {error}"[-500:]
            enabled = []
    context["stageTimingsMs"]["workerTotal"] = round((time.perf_counter() - started) * 1000, 3)
    report.update(optimizationProfile=decision.profile, fallbackReason=decision.fallback_reason,
                  features=enabled, stageTimingsMs=context["stageTimingsMs"], cacheStats=context["cacheStats"])
    return result, report

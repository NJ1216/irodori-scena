"""Validated, request-scoped PEFT adaptation of a nonquantized MLX model."""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

BASE_REPO = "Aratako/Irodori-TTS-v4.1-Small"
BASE_REVISION = "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
FP16_REPO = "mlx-community/Irodori-TTS-v4.1-Small-fp16"
FP16_REVISION = "8be8d91091380115f1ac77aeb6604ed588d05372"
FP16_CONFIG_SHA256 = "1fd3b64b681229e5226a873de625589aa0fffc865c0404389b92e917c8c6708b"
FP16_SHA256 = "99e022893ed27353aea6fca3897ee94c62bbaa568d705d230ee9b69f80a3a3bf"
BASE_SHA256 = "c85de88c01700cb53538e706f128ebcb1b8513ad21d7d0e75f58bc82cdbf89f6"


class RestorationError(RuntimeError):
    """Fatal: never continue a worker whose base restoration failed."""


ATTENTION_TARGET = re.compile(r"model\.blocks\.\d+\.attention\.(wq|wk|wv|wo|wk_text|wv_text|wk_speaker|wv_speaker|wk_caption|wv_caption|gate)\.weight$")


def verify_base_checkpoint(checkpoint: Path) -> None:
    if not checkpoint.is_file():
        raise ValueError("The shared official FP32 checkpoint is missing.")
    digest = hashlib.sha256()
    with checkpoint.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != BASE_SHA256:
        raise ValueError("The official FP32 checkpoint hash is incompatible.")


def supports_lora_model(model: dict[str, Any]) -> bool:
    origin = (model.get("baseModelRepo") or model.get("repo"),
              model.get("baseModelRevision") or model.get("revision"))
    if origin != (BASE_REPO, BASE_REVISION) or model.get("backend") != "mlx" or model.get("quantization"):
        return False
    artifact = (model.get("repo"), model.get("revision"))
    if model.get("variantId") == "mlx-fp32":
        return model.get("precision") == "FP32" and artifact == (BASE_REPO, BASE_REVISION)
    return (model.get("variantId") == "mlx-fp16" and model.get("precision") == "FP16"
            and artifact == (FP16_REPO, FP16_REVISION))


def verify_fp16_checkpoint(checkpoint: Path) -> None:
    for path, expected in ((checkpoint, FP16_SHA256), (checkpoint.parent / "config.json", FP16_CONFIG_SHA256)):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError(f"The pinned MLX FP16 asset hash is incompatible: {path.name}")


def adapter_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in ("adapter_config.json", "adapter_model.safetensors"):
        with (directory / name).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def validate_config(config: dict[str, Any]) -> tuple[int, float]:
    forbidden = ("use_dora", "use_rslora", "use_qalora", "fan_in_fan_out", "rank_pattern", "alpha_pattern",
                 "lora_bias", "layer_replication", "target_parameters", "trainable_token_indices",
                 "alora_invocation_tokens", "megatron_config", "arrow_config", "corda_config")
    if any(config.get(key) for key in forbidden):
        raise ValueError("This PEFT configuration is not supported by SCENA MLX LoRA.")
    if config.get("peft_type") != "LORA" or config.get("bias", "none") != "none":
        raise ValueError("Only standard bias-free LoRA is supported.")
    if (config.get("modules_to_save") or []) != ["duration_predictor"]:
        raise ValueError("Only the official duration_predictor modules_to_save contract is supported.")
    rank = config.get("r")
    alpha = config.get("lora_alpha")
    if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 256:
        raise ValueError("Invalid LoRA rank.")
    if isinstance(alpha, bool) or not isinstance(alpha, (int, float)) or not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("Invalid LoRA alpha.")
    return rank, float(alpha) / rank


def target_name(name: str) -> str:
    prefix = "base_model.model."
    if not name.startswith(prefix):
        raise ValueError(f"Unexpected adapter tensor prefix: {name}")
    return "model." + name[len(prefix):]


def _pair_update(key, weights, base, rank, scale, arrays):
    stem = key.removesuffix(".lora_A.weight")
    b_key = stem + ".lora_B.weight"
    if b_key not in weights:
        raise ValueError(f"Missing LoRA B tensor: {key}")
    a, b = weights[key], weights[b_key]
    target = target_name(stem + ".weight")
    if target not in base or not ATTENTION_TARGET.fullmatch(target):
        raise ValueError(f"Unsupported LoRA target: {target}")
    if len(a.shape) != 2 or len(b.shape) != 2 or a.shape[0] != rank or b.shape[1] != rank:
        raise ValueError(f"LoRA rank or dimensions mismatch: {key}")
    if (b.shape[0], a.shape[1]) != base[target].shape:
        raise ValueError(f"LoRA shape mismatch: {target}")
    updated = base[target].astype(arrays.float32) + scale * (b.astype(arrays.float32) @ a.astype(arrays.float32))
    return target, updated.astype(base[target].dtype), b_key


def require_unquantized_base(base, arrays):
    if any(value.dtype not in (arrays.float32, arrays.float16) for key, value in base.items() if key.startswith("model.")):
        raise ValueError("LoRA requires an unquantized FP32 or FP16 base model.")


def build_updates(base, weights, config, arrays):
    """Build the entire mutation plan before touching model parameters."""
    rank, scale = validate_config(config)
    require_unquantized_base(base, arrays)
    updates, consumed = {}, set()
    pairs = 0
    for key, value in weights.items():
        if not bool(arrays.all(arrays.isfinite(value)).item()):
            raise ValueError(f"Non-finite adapter tensor: {key}")
        if key.endswith(".lora_A.weight"):
            target, updated, b_key = _pair_update(key, weights, base, rank, scale, arrays)
            if target in updates:
                raise ValueError(f"Duplicate adapter destination: {target}")
            updates[target] = updated
            consumed.update((key, b_key))
            pairs += 1
    for key, value in weights.items():
        if key in consumed:
            continue
        target = target_name(key)
        if not target.startswith("model.duration_predictor.") or target not in base:
            raise ValueError(f"Unknown adapter tensor: {key}")
        if value.shape != base[target].shape or target in updates:
            raise ValueError(f"Invalid full-module destination: {key}")
        updates[target] = value.astype(base[target].dtype)
        consumed.add(key)
    expected_pairs = {key for key in base if ATTENTION_TARGET.fullmatch(key)}
    if not expected_pairs.issubset(updates):
        raise ValueError("Incomplete adapter: the official attention target set is required.")
    duration_keys = {key for key in base if key.startswith("model.duration_predictor.")}
    if not pairs or not duration_keys or not duration_keys.issubset(updates) or consumed != set(weights):
        raise ValueError("Incomplete adapter: all duration tensors and complete A/B pairs are required.")
    if any(not bool(arrays.all(arrays.isfinite(value)).item()) for value in updates.values()):
        raise ValueError("Adapter produced non-finite model weights.")
    # Keep validating every saved tensor, but apply only the voice adaptation.
    # Duration remains the untouched base predictor for legacy and mixed LoRAs.
    return {key: value for key, value in updates.items() if not key.startswith("model.duration_predictor.")}


def blend_updates(base, plans, arrays):
    """Interpolate attention deltas; duration adaptation is deliberately zero."""
    updates = {}
    for weight, plan in plans:
        for key, value in plan.items():
            if key.startswith("model.duration_predictor."):
                continue
            original = base[key].astype(arrays.float32)
            current = updates.get(key, original)
            updates[key] = current + weight * (value.astype(arrays.float32) - original)
    if any(not bool(arrays.all(arrays.isfinite(value)).item()) for value in updates.values()):
        raise ValueError("Mixture produced non-finite model weights.")
    return {key: value.astype(base[key].dtype) for key, value in updates.items()}


def install_empty_caption_compatibility(model, *, arrays=None) -> None:
    """Avoid an all-masked pretrained attention encoder for an absent caption.

    mlx-audio 0.5.0 encodes the BOS token with an all-false mask. ModernBERT
    produces NaN for that attention row; masking the resulting NaN is not zero.
    Keep the absent condition's original mask and supply a finite zero state.
    This changes no user caption and adds no synthetic conditioning tokens.
    """
    if arrays is None:
        import mlx.core as arrays
    inner = model.model
    if getattr(inner, "_scena_empty_caption_compatibility", False):
        return
    original = inner._encode_caption
    dimension = int(inner.cfg.caption_dim_resolved)
    dtype = inner.caption_norm.weight.dtype

    def encode_caption(input_ids, mask):
        if not bool(arrays.any(mask)):
            return arrays.zeros((*input_ids.shape, dimension), dtype=dtype)
        return original(input_ids, mask)

    inner._encode_caption = encode_caption
    inner._scena_empty_caption_compatibility = True


class AdapterSession:
    def __init__(self, model, *, arrays=None, flatten=None):
        if arrays is None:
            import mlx.core as arrays
        if flatten is None:
            from mlx.utils import tree_flatten as flatten
        self.model, self.arrays = model, arrays
        self.base = dict(flatten(model.parameters()))
        self.changed: set[str] = set()

    def restore(self):
        if self.changed:
            try:
                self.model.load_weights([(key, self.base[key]) for key in self.changed], strict=False)
                self.arrays.eval(*[self.base[key] for key in self.changed])
            except Exception as error:
                raise RestorationError("Base restoration failed; worker must be discarded.") from error
            self.changed.clear()

    def load_adapter(self, descriptor, base=None):
        if (descriptor.get("baseModelRepo"), descriptor.get("baseModelRevision")) != (BASE_REPO, BASE_REVISION):
            raise ValueError("Adapter base model identity is incompatible.")
        directory = Path(descriptor["path"])
        expected = descriptor.get("adapterHash")
        if not expected or adapter_digest(directory) != expected:
            raise ValueError("Adapter files changed or their hash is invalid.")
        config = json.loads((directory / "adapter_config.json").read_text(encoding="utf-8"))
        weights = self.arrays.load(str(directory / "adapter_model.safetensors"))
        updates = build_updates(self.base if base is None else base, weights, config, self.arrays)
        if adapter_digest(directory) != expected:
            raise ValueError("Adapter files changed while loading.")
        return updates

    def prepare(self, descriptor):
        if "adapters" not in descriptor:
            return self.load_adapter(descriptor)
        adapters = descriptor["adapters"]
        base_weight = descriptor.get("baseWeight")
        weights = [item.get("weight") for item in adapters]
        if (type(base_weight) is not int or not 0 <= base_weight <= 10000
                or len(adapters) > 4 or any(type(w) is not int or not 0 <= w <= 10000 for w in weights)
                or base_weight + sum(weights) != 10000):
            raise ValueError("Invalid adapter mixture.")
        positive = [item for item in adapters if item["weight"] > 0]
        if not positive:
            return {}
        # Preserve the attention endpoint including FP16 rounding exactly.
        if len(positive) == 1 and positive[0]["weight"] == 10000:
            return self.load_adapter(positive[0])
        require_unquantized_base(self.base, self.arrays)
        fp32 = {key: value.astype(self.arrays.float32) for key, value in self.base.items()}
        plans = [(item["weight"] / 10000, self.load_adapter(item, fp32)) for item in positive]
        return blend_updates(self.base, plans, self.arrays)

    @contextlib.contextmanager
    def scoped(self, descriptor):
        self.restore()
        try:
            if descriptor:
                updates = self.prepare(descriptor)
                self.arrays.eval(*updates.values())
                # Mark before mutation so a partial load failure is reversible.
                self.changed = set(updates)
                self.model.load_weights(list(updates.items()), strict=False)
            yield
        finally:
            self.restore()

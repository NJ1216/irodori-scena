"""Strict non-pickle PEFT validation against the pinned base tensor inventory."""
from __future__ import annotations
import json
import math
import re
import struct
import sys
from array import array
from pathlib import Path

TARGET_PATTERN = r"^blocks\.\d+\.attention\.(wq|wk|wv|wo|wk_text|wv_text|wk_speaker|wv_speaker|wk_caption|wv_caption|gate)$"
CONFIG_KEYS = set("alora_invocation_tokens alpha_pattern arrow_config auto_mapping base_model_name_or_path bias corda_config ensure_weight_tying eva_config exclude_modules fan_in_fan_out inference_mode init_lora_weights layer_replication layers_pattern layers_to_transform loftq_config lora_alpha lora_bias lora_dropout megatron_config megatron_core modules_to_save peft_type peft_version qalora_group_size r rank_pattern revision target_modules target_parameters task_type trainable_token_indices use_dora use_qalora use_rslora".split())


def safe_header(path: Path) -> tuple[dict, int]:
    with path.open("rb") as stream:
        raw = stream.read(8)
        if len(raw) != 8:
            raise ValueError("Truncated safetensors")
        length = struct.unpack("<Q", raw)[0]
        if length > 8 * 1024 * 1024 or length < 2:
            raise ValueError("Invalid safetensors header length")
        header = json.loads(stream.read(length), object_pairs_hook=_unique)
    if not isinstance(header, dict):
        raise ValueError("Invalid safetensors header")
    return header, 8 + length


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _config(path: Path) -> dict:
    if path.stat().st_size > 65536:
        raise ValueError("Adapter config too large")
    config = json.loads(path.read_text(), object_pairs_hook=_unique)
    if not isinstance(config, dict) or set(config) - CONFIG_KEYS:
        raise ValueError("Unknown adapter configuration")
    disabled = "alora_invocation_tokens alpha_pattern arrow_config corda_config ensure_weight_tying eva_config exclude_modules fan_in_fan_out layer_replication layers_pattern layers_to_transform loftq_config lora_bias megatron_config rank_pattern target_parameters trainable_token_indices use_dora use_qalora use_rslora"
    if any(config.get(key) for key in disabled.split()):
        raise ValueError("Unsupported PEFT variant")
    if config.get("peft_type") != "LORA" or config.get("bias", "none") != "none":
        raise ValueError("Expected bias-free LORA")
    if config.get("target_modules") != TARGET_PATTERN or config.get("modules_to_save") != ["duration_predictor"]:
        raise ValueError("Only tested diffusion attention and duration predictor are supported")
    rank, alpha = config.get("r"), config.get("lora_alpha")
    if isinstance(rank, bool) or not isinstance(rank, int) or not 1 <= rank <= 128:
        raise ValueError("Invalid LoRA rank")
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or not math.isfinite(alpha) or not 0 < alpha <= 1024:
        raise ValueError("Invalid LoRA alpha")
    return config


def _check_tensor(stream, value: dict, offset: int, file_size: int) -> tuple[int, int]:
    if not isinstance(value, dict) or value.get("dtype") != "F32":
        raise ValueError("Only FP32 adapter tensors are supported")
    shape, bounds = value.get("shape"), value.get("data_offsets")
    if not isinstance(shape, list) or not shape or any(type(d) is not int or d <= 0 for d in shape):
        raise ValueError("Invalid tensor shape")
    if not isinstance(bounds, list) or len(bounds) != 2 or any(type(d) is not int for d in bounds):
        raise ValueError("Invalid tensor offsets")
    start, end = bounds
    if start < 0 or end - start != math.prod(shape) * 4 or offset + end > file_size:
        raise ValueError("Truncated adapter tensor")
    stream.seek(offset + start)
    remaining = end - start
    while remaining:
        data = stream.read(min(remaining, 1024 * 1024))
        if not data or len(data) % 4 or not _all_finite_f32(data):
            raise ValueError("Adapter contains invalid floating-point values")
        remaining -= len(data)
    return start, end


def _all_finite_f32(data: bytes) -> bool:
    values = array("f")
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    return all(map(math.isfinite, values))


def validate_adapter(directory: Path, checkpoint: Path) -> dict:
    config = _config(directory / "adapter_config.json")
    path = directory / "adapter_model.safetensors"
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError("Adapter too large")
    tensors, offset = safe_header(path)
    base, _ = safe_header(checkpoint)
    tensors.pop("__metadata__", None)
    expected = _expected_shapes(base, config["r"])
    if set(tensors) != set(expected):
        raise ValueError("Missing or unknown adapter tensor")
    spans = []
    with path.open("rb") as stream:
        for name, value in tensors.items():
            if not isinstance(value, dict) or value.get("shape") != expected[name]:
                raise ValueError(f"Adapter shape mismatch: {name}")
            spans.append(_check_tensor(stream, value, offset, path.stat().st_size))
    spans.sort()
    cursor = 0
    for start, end in spans:
        if start != cursor:
            raise ValueError("Overlapping or noncontiguous tensor payload")
        cursor = end
    if offset + cursor != path.stat().st_size:
        raise ValueError("Unexpected trailing adapter payload")
    return {"tensorCount": len(tensors), "rank": config["r"], "alpha": config["lora_alpha"]}


def _expected_shapes(base: dict, rank: int) -> dict:
    expected = {}
    for name, value in base.items():
        if name == "__metadata__":
            continue
        if not isinstance(value, dict) or not isinstance(value.get("shape"), list):
            raise ValueError("Invalid base tensor header")
        stem = name.removesuffix(".weight")
        if name.endswith(".weight") and re.fullmatch(TARGET_PATTERN, stem):
            rows, columns = value["shape"]
            expected[f"base_model.model.{stem}.lora_A.weight"] = [rank, columns]
            expected[f"base_model.model.{stem}.lora_B.weight"] = [rows, rank]
        elif name.startswith("duration_predictor."):
            expected[f"base_model.model.{name}"] = value["shape"]
    if not expected:
        raise ValueError("Invalid base tensor inventory")
    return expected

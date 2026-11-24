"""Restricted RF sampler used by SCENA's verified MPS/CUDA adapter.

It intentionally supports only the inference shape emitted by SCENA.  Keeping
this surface small makes an unknown upstream API fail closed to eager mode.
"""

from __future__ import annotations

import math
import time
from typing import Any

_UI_ACTIVITY_UNTIL = 0.0


def note_ui_activity() -> None:
    global _UI_ACTIVITY_UNTIL
    _UI_ACTIVITY_UNTIL = max(_UI_ACTIVITY_UNTIL, time.monotonic() + 0.25)


def wait_for_ui_idle(torch: Any, device: Any = "mps") -> None:
    if str(device) != "mps":
        return
    if time.monotonic() >= _UI_ACTIVITY_UNTIL:
        return
    if hasattr(torch, "mps"):
        torch.mps.synchronize()
    while True:
        remaining = _UI_ACTIVITY_UNTIL - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.016, remaining))


def _cat(torch: Any, values: list[Any | None]) -> Any | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    if len(present) != len(values):
        raise ValueError("SCENA condition bundle has mixed optional values.")
    return torch.cat(present, dim=0)


def _rng(torch: Any, seed: int, device: Any) -> tuple[Any, Any]:
    try:
        return torch.Generator(device=device).manual_seed(seed), device
    except RuntimeError:
        cpu = torch.device("cpu")
        return torch.Generator(device=cpu).manual_seed(seed), cpu


def _context_caches(model: Any, encoded: tuple[Any, ...], conditional: tuple[Any, ...],
                    enabled: bool) -> tuple[Any | None, Any | None]:
    if not enabled:
        return None, None
    bundled = model.build_context_kv_cache(
        text_state=encoded[0], speaker_state=encoded[2], caption_state=encoded[4]
    )
    condition_only = model.build_context_kv_cache(
        text_state=conditional[0], speaker_state=conditional[2], caption_state=conditional[4]
    )
    return bundled, condition_only


def sample_euler_rf_cfg(**args: Any) -> Any:
    """Run SCENA's independent-CFG path with one initial schedule sync."""
    import torch

    model = args["model"]
    if args.get("cfg_guidance_mode", "independent") != "independent":
        raise ValueError("SCENA optimized sampling supports independent CFG only.")
    if args.get("speaker_uncond_mode", "mask") != "mask":
        raise ValueError("SCENA optimized sampling supports masked speaker CFG only.")
    if any(args.get(name) is not None for name in ("cfg_scale", "rescale_k", "rescale_sigma", "speaker_kv_scale")):
        raise ValueError("SCENA optimized sampling received an unsupported advanced option.")

    device, dtype = model.device, model.dtype
    text_ids, text_mask = args["text_input_ids"], args["text_mask"]
    batch_size = text_ids.shape[0]
    generator, generator_device = _rng(torch, int(args.get("seed", 0)), device)
    latent = torch.randn(
        (batch_size, int(args["sequence_length"]), model.cfg.patched_latent_dim),
        device=generator_device,
        dtype=dtype,
        generator=generator,
    )
    if generator_device != device:
        latent = latent.to(device=device)
    truncation = args.get("truncation_factor")
    if truncation is not None:
        latent = latent * float(truncation)

    steps = int(args.get("num_steps", 40))
    schedule_mode = str(args.get("t_schedule_mode", "linear")).strip().lower()
    unit = torch.linspace(0.0, 1.0, steps + 1, device=device)
    if schedule_mode == "sway":
        sway = float(args.get("sway_coeff", -1.0))
        if not math.isfinite(sway):
            raise ValueError("sway coefficient must be finite.")
        unit = unit + sway * (torch.cos(0.5 * math.pi * unit) + unit - 1.0)
        unit = unit.clamp(0.0, 1.0)
    elif schedule_mode != "linear":
        raise ValueError("SCENA optimized sampling supports linear or sway schedules.")
    schedule = (1.0 - unit) * 0.999
    # One synchronization supplies all control-flow values. Tensor arithmetic
    # continues to use the original MPS schedule, preserving its exact values.
    controls = schedule.detach().to("cpu").tolist()
    if any(left <= right for left, right in zip(controls, controls[1:])):
        raise ValueError("RF schedule must be strictly decreasing.")

    conditions = model.encode_conditions(
        text_input_ids=text_ids,
        text_mask=text_mask,
        ref_latent=args.get("ref_latent"),
        ref_mask=args.get("ref_mask"),
        caption_input_ids=args.get("caption_input_ids"),
        caption_mask=args.get("caption_mask"),
        speaker_state_override=args.get("speaker_state_override"),
        speaker_mask_override=args.get("speaker_mask_override"),
        speaker_uncond_mode="mask",
    )
    text_state, text_mask_cond, speaker_state, speaker_mask, caption_state, caption_mask = conditions
    scales = {
        "text": float(args.get("cfg_scale_text", 3.0)),
        "speaker": float(args.get("cfg_scale_speaker", 5.0)) if model.cfg.use_speaker_condition_resolved else 0.0,
        "caption": float(args.get("cfg_scale_caption", 3.0)) if model.cfg.use_caption_condition else 0.0,
    }
    caption_enabled = bool(caption_mask is not None and caption_mask.any().detach().to("cpu").item())
    names = [name for name in ("text", "speaker", "caption") if scales[name] > 0 and (name != "caption" or caption_enabled)]
    zero_text, zero_text_mask = torch.zeros_like(text_state), torch.zeros_like(text_mask_cond)
    zero_speaker = torch.zeros_like(speaker_state) if speaker_state is not None else None
    zero_speaker_mask = torch.zeros_like(speaker_mask) if speaker_mask is not None else None
    zero_caption = torch.zeros_like(caption_state) if caption_state is not None else None
    zero_caption_mask = torch.zeros_like(caption_mask) if caption_mask is not None else None

    bundles = [(text_state, text_mask_cond, speaker_state, speaker_mask, caption_state, caption_mask)]
    for name in names:
        bundles.append((
            zero_text if name == "text" else text_state,
            zero_text_mask if name == "text" else text_mask_cond,
            zero_speaker if name == "speaker" else speaker_state,
            zero_speaker_mask if name == "speaker" else speaker_mask,
            zero_caption if name == "caption" else caption_state,
            zero_caption_mask if name == "caption" else caption_mask,
        ))
    encoded = (
        torch.cat([item[0] for item in bundles], dim=0),
        torch.cat([item[1] for item in bundles], dim=0),
        _cat(torch, [item[2] for item in bundles]),
        _cat(torch, [item[3] for item in bundles]),
        _cat(torch, [item[4] for item in bundles]),
        _cat(torch, [item[5] for item in bundles]),
    )
    kv_cache, conditional_kv_cache = _context_caches(
        model, encoded, conditions, bool(args.get("use_context_kv_cache", True))
    )
    # The bundled cache is used while CFG is active.  Outside the CFG window we
    # still pass a conditional-only cache: omitting it makes the upstream
    # forward rebuild context K/V on every remaining RF step (notably half of
    # Linear 40 with the product's cfg_min_t=0.5 setting).
    cfg_min, cfg_max = float(args.get("cfg_min_t", 0.5)), float(args.get("cfg_max_t", 1.0))

    for index, control in enumerate(controls[:-1]):
        wait_for_ui_idle(torch, device)
        current, following = schedule[index], schedule[index + 1]
        timestep = torch.full((batch_size,), current, device=device, dtype=dtype)
        if names and cfg_min <= control <= cfg_max:
            repeated_latent = torch.cat([latent] * len(bundles), dim=0).to(dtype)
            velocity_parts = model.forward_with_encoded_conditions(
                x_t=repeated_latent,
                t=timestep.repeat(len(bundles)),
                text_state=encoded[0], text_mask=encoded[1],
                speaker_state=encoded[2], speaker_mask=encoded[3],
                caption_state=encoded[4], caption_mask=encoded[5],
                context_kv_cache=kv_cache,
            ).chunk(len(bundles), dim=0)
            velocity = velocity_parts[0]
            for name, unconditioned in zip(names, velocity_parts[1:], strict=True):
                velocity = velocity + scales[name] * (velocity_parts[0] - unconditioned)
        else:
            velocity = model.forward_with_encoded_conditions(
                x_t=latent.to(dtype), t=timestep,
                text_state=text_state, text_mask=text_mask_cond,
                speaker_state=speaker_state, speaker_mask=speaker_mask,
                caption_state=caption_state, caption_mask=caption_mask,
                context_kv_cache=conditional_kv_cache,
            )
        latent = latent + velocity * (following - current)
    return latent

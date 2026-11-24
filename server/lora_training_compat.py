"""Fingerprint-bound MPS metric compatibility for the immutable upstream trainer.

Only aggregations change FP64 to FP32. Architecture/loss/optimizer remain upstream.
The reviewed source is compiled in memory; no managed-engine file is written.
"""
from __future__ import annotations
import hashlib
import json

TRAIN_SHA256 = "4e55e0e1e2f3da21830020e4e36ad8ef0cc39f4c47d1206f17f5dc80fb7342c4"


def compatible_trainer(source: bytes, adapter_path: str | None = None) -> str:
    if hashlib.sha256(source).hexdigest() != TRAIN_SHA256:
        raise ValueError("Unreviewed trainer fingerprint")
    text = source.decode("utf-8")
    if text.count("dtype=torch.float64") != 4 or text.count(".double()") != 7:
        raise ValueError("Unexpected metric patch inventory")
    text = text.replace("dtype=torch.float64", "dtype=torch.float32").replace(".double()", ".float()")
    marker = "                optimizer.step()\n"
    if text.count(marker) != 1:
        raise ValueError("Unexpected optimizer publication site")
    publication = (
        "                _scena_grads = [p.grad for p in model.parameters() if p.requires_grad and p.grad is not None]\n"
        "                if not torch.isfinite(step_loss).all() or not all(torch.isfinite(g).all() for g in _scena_grads):\n"
        "                    raise RuntimeError('Non-finite training loss or gradient')\n"
        + marker +
        "                print('SCENA_PROGRESS ' + json.dumps({'stage': 'training', 'step': step + 1, 'loss': float(step_loss.item())}), flush=True)\n"
    )
    text = text.replace(marker, publication)
    if adapter_path:
        initialization = "        if train_config_uses_lora(train_cfg) and not lora_wrapped:\n            raw_model = apply_lora(raw_model, train_cfg)"
        if text.count(initialization) != 1:
            raise ValueError("Unexpected adapter initialization site")
        text = text.replace(initialization, "        if train_config_uses_lora(train_cfg) and not lora_wrapped:\n            raw_model = load_lora_adapter(raw_model, Path(" + json.dumps(adapter_path) + "), is_trainable=True)")
    return text

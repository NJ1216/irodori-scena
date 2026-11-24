"""Small in-repository probes for validating the MPS compile harness itself."""

from __future__ import annotations

import math
from typing import Any


def pointwise_probe(torch: Any, device: Any):
    def operation(value):
        return torch.sin(value) * 0.5 + value.square()

    def make_args(shape: tuple[int, ...]):
        count = math.prod(shape)
        return (torch.arange(count, device=device, dtype=torch.float32).reshape(shape) / max(1, count),)

    return operation, make_args

"""Skip overwritten random parameter initialization for one verified Windows runtime."""
from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Iterator

ENGINE = "8224dafb46d0aba89209a8f905f1cb7e3299d9c1"
MODEL = "Aratako/Irodori-TTS-v4.1-Small@2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
_RANDOM_INITIALIZERS = (
    "kaiming_uniform_", "kaiming_normal_", "xavier_uniform_", "xavier_normal_",
    "trunc_normal_", "normal_", "uniform_", "orthogonal_",
)


def eligible(*, engine_commit: str | None, model_identity: str | None, device: str) -> bool:
    return sys.platform == "win32" and engine_commit == ENGINE and model_identity == MODEL and device == "cuda"


def get_runtime(*, upstream: Any, torch: Any, get_cached: Any, key: Any,
                engine_commit: str | None, model_identity: str | None, device: str) -> Any:
    if eligible(engine_commit=engine_commit, model_identity=model_identity, device=device):
        with skip_overwritten_initialization(upstream, torch):
            return get_cached(key)
    return get_cached(key)


@contextmanager
def skip_overwritten_initialization(upstream: Any, torch: Any) -> Iterator[None]:
    """Scope the patch to model construction; strict upstream state loading follows it."""
    constructor = upstream.TextToLatentRFDiT
    originals = {name: getattr(torch.nn.init, name) for name in _RANDOM_INITIALIZERS}

    def construct(*args: Any, **kwargs: Any) -> Any:
        try:
            for name in _RANDOM_INITIALIZERS:
                setattr(torch.nn.init, name, lambda tensor, *a, **kw: tensor)
            return constructor(*args, **kwargs)
        finally:
            for name, original in originals.items():
                setattr(torch.nn.init, name, original)

    upstream.TextToLatentRFDiT = construct
    try:
        yield
    finally:
        upstream.TextToLatentRFDiT = constructor
        for name, original in originals.items():
            setattr(torch.nn.init, name, original)

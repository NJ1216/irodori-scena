"""Per-generation CUDA Graph replay for the RF forward of the verified engine.

Each generation reuses the same condition tensors and context K/V for all RF
steps, so one recorded forward per batch shape replays every step with the
same kernels and therefore the same output.  Graphs never outlive the
generation that recorded them, so tensor identities cannot go stale.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterator

# Capture cost outweighs replay savings for FP32 at fewer steps (measured on RTX 4070 Ti).
FP32_MINIMUM_STEPS = 16


def use_step_graphs(variant_id: str, steps: int) -> bool:
    return variant_id != "pytorch-fp32" or steps >= FP32_MINIMUM_STEPS


class StepGraphs:
    """Replace forward_with_encoded_conditions with recorded replays keyed by input identity."""

    def __init__(self, torch: Any, forward: Callable[..., Any], warmups: int = 1) -> None:
        self.torch, self.forward, self.warmups = torch, forward, warmups
        self.pool = torch.cuda.graph_pool_handle()
        # Each entry also holds its fixed inputs, so their ids cannot be reused while it exists.
        self.entries: dict[tuple[Any, ...], tuple[Any, Any, Any, Any, dict[str, Any]]] = {}

    def __call__(self, **kwargs: Any) -> Any:
        x_t, t = kwargs["x_t"], kwargs["t"]
        fixed = {name: value for name, value in kwargs.items() if name not in ("x_t", "t")}
        key = (tuple(x_t.shape), str(x_t.dtype), tuple(t.shape)) + tuple((name, id(value)) for name, value in sorted(fixed.items()))
        entry = self.entries.get(key)
        if entry is None:
            entry = self.entries[key] = self._record(x_t, t, fixed)
        graph, static_x, static_t, output, _fixed = entry
        static_x.copy_(x_t)
        static_t.copy_(t)
        graph.replay()
        return output

    def _record(self, x_t: Any, t: Any, fixed: dict[str, Any]) -> tuple[Any, Any, Any, Any, dict[str, Any]]:
        torch = self.torch
        static_x, static_t = x_t.clone(), t.clone()
        side = torch.cuda.Stream()
        side.wait_stream(torch.cuda.current_stream())
        with torch.cuda.stream(side):
            for _ in range(self.warmups):
                self.forward(x_t=static_x, t=static_t, **fixed)
        torch.cuda.current_stream().wait_stream(side)
        graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(graph, pool=self.pool):
            output = self.forward(x_t=static_x, t=static_t, **fixed)
        return graph, static_x, static_t, output, fixed


def cached_timestep_embedding(torch: Any, upstream: Callable[[Any, int], Any]) -> Callable[[Any, int], Any]:
    """Upstream arithmetic with the frequency vector built once, outside capture."""
    frequencies: dict[tuple[str, int], Any] = {}

    def embedding(timestep: Any, dim: int) -> Any:
        assert dim % 2 == 0
        key = (str(timestep.device), dim)
        freqs = frequencies.get(key)
        if freqs is None:
            half = dim // 2
            freqs = frequencies[key] = 1000.0 * torch.exp(
                -torch.log(torch.tensor(10000.0, device=timestep.device, dtype=torch.float32))
                * torch.arange(half, device=timestep.device, dtype=torch.float32)
                / half
            )
        args = timestep[:, None].float() * freqs[None, :]
        return torch.cat([torch.cos(args), torch.sin(args)], dim=-1).to(timestep.dtype)

    embedding.upstream = upstream  # type: ignore[attr-defined]
    return embedding


@contextmanager
def step_graphs(torch: Any, model: Any, forward: Callable[..., Any]) -> Iterator[StepGraphs]:
    """Patch the model module's timestep embedding for the generation and yield the replaying forward."""
    module = sys.modules[type(model).__module__]
    upstream = module.get_timestep_embedding
    module.get_timestep_embedding = cached_timestep_embedding(torch, upstream)
    graphs = StepGraphs(torch, forward)
    try:
        yield graphs
    finally:
        module.get_timestep_embedding = upstream
        graphs.entries.clear()

from __future__ import annotations

import contextlib
import sys
import types
import unittest
from types import SimpleNamespace

from server.irodori_cuda_graphs import StepGraphs, step_graphs, use_step_graphs


class _Tensor:
    def __init__(self, value, shape=(2, 4)):
        self.value, self.shape, self.dtype = value, shape, "float32"

    def clone(self):
        return _Tensor(self.value, self.shape)

    def copy_(self, other):
        self.value = other.value
        return self


class _Graph:
    def __init__(self):
        self.replays = 0

    def replay(self):
        self.replays += 1


class _Cuda:
    def __init__(self):
        self.graphs = []

    def graph_pool_handle(self):
        return "pool"

    def Stream(self):  # noqa: N802 - mirrors torch.cuda.Stream
        return SimpleNamespace(wait_stream=lambda _other: None)

    def current_stream(self):
        return SimpleNamespace(wait_stream=lambda _other: None)

    def stream(self, _stream):
        return contextlib.nullcontext()

    def CUDAGraph(self):  # noqa: N802 - mirrors torch.cuda.CUDAGraph
        graph = _Graph()
        self.graphs.append(graph)
        return graph

    def graph(self, _graph, pool=None):
        assert pool == "pool"
        return contextlib.nullcontext()


class StepGraphTests(unittest.TestCase):
    def test_fp32_skips_graphs_below_16_steps_and_quantized_always_uses_them(self) -> None:
        self.assertFalse(use_step_graphs("pytorch-fp32", 8))
        self.assertTrue(use_step_graphs("pytorch-fp32", 16))
        self.assertTrue(use_step_graphs("pytorch-w8a16", 8))
        self.assertTrue(use_step_graphs("pytorch-w4a16", 8))

    def test_one_recording_replays_every_step_with_the_current_inputs(self) -> None:
        torch = SimpleNamespace(cuda=_Cuda())
        calls = []
        graphs = StepGraphs(torch, lambda **kw: calls.append(kw["x_t"].value) or "output")
        kv, text = object(), object()
        for step in range(3):
            self.assertEqual(graphs(x_t=_Tensor(step), t=_Tensor(step, (2,)), context_kv_cache=kv, text_state=text), "output")
        self.assertEqual(len(torch.cuda.graphs), 1)
        self.assertEqual(torch.cuda.graphs[0].replays, 3)
        self.assertEqual(calls, [0, 0])
        (_graph, static_x, static_t, _output, _fixed), = graphs.entries.values()
        self.assertEqual((static_x.value, static_t.value), (2, 2))

    def test_new_condition_tensors_or_batch_shapes_record_separately(self) -> None:
        torch = SimpleNamespace(cuda=_Cuda())
        graphs = StepGraphs(torch, lambda **_kw: "output")
        text = object()
        graphs(x_t=_Tensor(0), t=_Tensor(0, (2,)), context_kv_cache=object(), text_state=text)
        graphs(x_t=_Tensor(0), t=_Tensor(0, (2,)), context_kv_cache=object(), text_state=text)
        graphs(x_t=_Tensor(0, (6, 4)), t=_Tensor(0, (6,)), context_kv_cache=None, text_state=text)
        self.assertEqual(len(torch.cuda.graphs), 3)

    def test_timestep_embedding_is_restored_and_graphs_are_dropped(self) -> None:
        module = types.ModuleType("fake_irodori_model")
        upstream = lambda timestep, dim: (timestep, dim)  # noqa: E731
        module.get_timestep_embedding = upstream
        sys.modules[module.__name__] = module
        try:
            model_type = type("Model", (), {"__module__": module.__name__})
            torch = SimpleNamespace(cuda=_Cuda())
            with step_graphs(torch, model_type(), lambda **_kw: "output") as graphs:
                self.assertIsNot(module.get_timestep_embedding, upstream)
                self.assertIs(module.get_timestep_embedding.upstream, upstream)
                graphs(x_t=_Tensor(0), t=_Tensor(0, (2,)), text_state=object())
            self.assertIs(module.get_timestep_embedding, upstream)
            self.assertEqual(graphs.entries, {})
        finally:
            del sys.modules[module.__name__]


if __name__ == "__main__":
    unittest.main()

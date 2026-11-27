from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server import irodori_load_adapter as adapter


class LoadAdapterTests(unittest.TestCase):
    def test_dispatch_patches_verified_runtime_and_preserves_unknown_fallback(self):
        init_namespace = SimpleNamespace(**{name: lambda tensor, *a, **kw: tensor
                                            for name in adapter._RANDOM_INITIALIZERS})
        torch = SimpleNamespace(nn=SimpleNamespace(init=init_namespace))
        def original():
            return None
        upstream = SimpleNamespace(TextToLatentRFDiT=original)
        observed = []

        def cached(key):
            observed.append((key, upstream.TextToLatentRFDiT is original))
            return "runtime", True

        with patch.object(adapter.sys, "platform", "win32"):
            result = adapter.get_runtime(upstream=upstream, torch=torch, get_cached=cached, key="key",
                                         engine_commit=adapter.ENGINE, model_identity=adapter.MODEL, device="cuda")
            self.assertEqual(result, ("runtime", True))
            adapter.get_runtime(upstream=upstream, torch=torch, get_cached=cached, key="key",
                                engine_commit="unknown", model_identity=adapter.MODEL, device="cuda")
        self.assertEqual(observed, [("key", False), ("key", True)])
        self.assertIs(upstream.TextToLatentRFDiT, original)

    def test_only_verified_windows_cuda_pair_is_eligible(self):
        with patch.object(adapter.sys, "platform", "win32"):
            self.assertTrue(adapter.eligible(engine_commit=adapter.ENGINE, model_identity=adapter.MODEL, device="cuda"))
            self.assertFalse(adapter.eligible(engine_commit="unknown", model_identity=adapter.MODEL, device="cuda"))
            self.assertFalse(adapter.eligible(engine_commit=adapter.ENGINE, model_identity="unknown", device="cuda"))
            self.assertFalse(adapter.eligible(engine_commit=adapter.ENGINE, model_identity=adapter.MODEL, device="cpu"))
        with patch.object(adapter.sys, "platform", "darwin"):
            self.assertFalse(adapter.eligible(engine_commit=adapter.ENGINE, model_identity=adapter.MODEL, device="cuda"))

    def test_initializer_is_scoped_to_construction_even_on_failure(self):
        calls = []
        def init(tensor, *_args, **_kwargs):
            calls.append(tensor)
            return tensor
        init_namespace = SimpleNamespace(**{name: init for name in adapter._RANDOM_INITIALIZERS})
        torch = SimpleNamespace(nn=SimpleNamespace(init=init_namespace))

        def constructor():
            self.assertIs(init_namespace.normal_(marker), marker)
            raise ValueError("construction failed")

        marker = object()
        upstream = SimpleNamespace(TextToLatentRFDiT=constructor)
        with self.assertRaisesRegex(ValueError, "construction failed"):
            with adapter.skip_overwritten_initialization(upstream, torch):
                upstream.TextToLatentRFDiT()
        self.assertIs(upstream.TextToLatentRFDiT, constructor)
        self.assertIs(init_namespace.normal_, init)
        self.assertEqual(calls, [])

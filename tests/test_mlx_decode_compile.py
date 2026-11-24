import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from server import mlx_acceleration_adapter as adapter
from server import mlx_decode_compile as decode_compile

RUNTIME = "mlx-audio@0.5.0"
HOP = 3
# numpy stands in for mlx.core, which the unit-test environment does not install.
XP = SimpleNamespace(linspace=lambda start, stop, count: np.linspace(start, stop, count, dtype=np.float32),
                     concatenate=lambda parts, axis: np.concatenate(parts, axis=axis), tanh=np.tanh,
                     transpose=np.transpose, eval=lambda *arrays: None, clear_cache=lambda: None)


class FakeDecoder:
    """Maps every frame to HOP samples of its first channel, so the decode is position-wise."""

    def __init__(self):
        self.snake_out = lambda value: value
        self.conv_out = lambda value: value

    def __call__(self, frames):
        return np.repeat(frames[..., :1], HOP, axis=1)


class FakeCodec:
    def __init__(self):
        self.hop_length = HOP
        self.quantizer_out_proj = lambda frames: frames
        self.decoder = FakeDecoder()
        self.plain_calls = []

    def decode(self, encoded_frames, chunk_size=None):
        self.plain_calls.append(chunk_size)
        return "plain"


def frames(total):
    values = np.sin(np.arange(total, dtype=np.float32) / 7.0)
    return np.stack([values, values * 2], axis=0)[None, :, :]  # (batch, codebook_dim, frames)


class ChunkedDecodeTest(unittest.TestCase):
    def test_crossfaded_chunks_equal_a_single_pass_for_a_position_wise_decoder(self):
        codec = FakeCodec()
        body = decode_compile.chunk_body(codec, XP)
        for total in (5, 50, 51, 96, 200, 377):
            with self.subTest(frames=total):
                encoded = frames(total)
                chunked = decode_compile.decode_chunked(encoded, 50, body, HOP, XP)
                single = body(np.transpose(encoded, (0, 2, 1)))
                self.assertEqual(chunked.shape, (1, total * HOP, 1))
                np.testing.assert_allclose(chunked, single, rtol=0, atol=1e-6)


class CompileDecodeFeatureTest(unittest.TestCase):
    def setUp(self):
        adapter.clear_caches()
        adapter.reset_failures()
        self.compiled = []

        def fake_compile(function):
            self.compiled.append(function)
            return function

        for target, value in (("_mx_compile", fake_compile), ("_xp", lambda: XP)):
            patcher = patch.object(decode_compile, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def model(self, codec):
        model = SimpleNamespace(dacvae=codec, decoded=[])

        def generate(**_kwargs):
            model.decoded.append(model.dacvae.decode(frames(120), chunk_size=50))
            yield SimpleNamespace(audio=[0.0], sample_rate=48000)

        model.generate = generate
        return model

    def run_feature(self, model):
        with patch.object(adapter, "select_profile", lambda *_args, **_kw: adapter.Decision(adapter.PROFILE, None)):
            return adapter.run(model, {"text": "テスト"}, runtime_version=RUNTIME, features=frozenset({"compile-decode"}), lora=False)[1]

    def test_chunk_body_is_compiled_once_per_codec_and_restored_after_the_call(self):
        codec = FakeCodec()
        model = self.model(codec)
        self.run_feature(model)
        report = self.run_feature(model)
        self.assertEqual(len(self.compiled), 1)
        self.assertEqual(report["cacheStats"]["compileDecode"], "compiled")
        self.assertEqual(model.decoded[-1].shape, (1, 120 * HOP, 1))
        self.assertEqual(codec.plain_calls, [])
        self.assertNotIn("decode", vars(codec))

    def test_clearing_caches_drops_the_compiled_body(self):
        model = self.model(FakeCodec())
        self.run_feature(model)
        adapter.clear_caches()
        self.run_feature(model)
        self.assertEqual(len(self.compiled), 2)

    def test_single_pass_decode_uses_the_plain_codec(self):
        codec = FakeCodec()
        wrapped = decode_compile.compiled_decode(codec, lambda chunk: chunk)
        self.assertEqual(wrapped(frames(10), chunk_size=None), "plain")
        self.assertEqual(codec.plain_calls, [None])

    def test_codec_without_the_expected_layers_keeps_the_plain_decode(self):
        codec = FakeCodec()
        del codec.quantizer_out_proj
        model = self.model(codec)
        report = self.run_feature(model)
        self.assertEqual(report["cacheStats"]["compileDecode"], "unsupported")
        self.assertEqual(model.decoded, ["plain"])
        self.assertEqual(self.compiled, [])


if __name__ == "__main__":
    unittest.main()

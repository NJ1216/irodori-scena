"""Compiled codec decode for the MLX acceleration adapter (feature ``compile-decode``).

mlx-audio decodes the latent in 50-frame chunks and evaluates each chunk, so the
whole decode cannot be compiled. This module compiles the per-chunk decoder
once per codec with ``shapeless=True`` (one trace covers every chunk length;
the shorter last chunk would otherwise trace again for each new line length)
and repeats the upstream chunk loop and crossfade around it.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, ContextManager, Iterator

Patcher = Callable[[Any, str, Callable[..., Any]], ContextManager[None]]

# Mirrors mlx_audio.codec.models.dacvae.codec.DACVAE._decode_chunked (mlx-audio 0.5.0).
_OVERLAP_FRAMES = 4
_COMPILED_BODIES: dict[int, Callable[[Any], Any]] = {}


def _xp() -> Any:
    import mlx.core as mx

    return mx


def _mx_compile(function: Callable[[Any], Any]) -> Callable[[Any], Any]:
    import mlx.core as mx

    return mx.compile(function, shapeless=True)


def clear() -> None:
    _COMPILED_BODIES.clear()


def chunk_body(codec: Any, xp: Any) -> Callable[[Any], Any]:
    def body(chunk: Any) -> Any:
        out = codec.decoder(codec.quantizer_out_proj(chunk))
        out = codec.decoder.snake_out(out)
        return xp.tanh(codec.decoder.conv_out(out))

    return body


def decode_chunked(encoded_frames: Any, chunk_size: int, body: Callable[[Any], Any], hop_length: int, xp: Any) -> Any:
    """Decode (batch, codebook_dim, frames) in overlapping chunks and crossfade them, as upstream does."""
    total_frames = encoded_frames.shape[2]
    encoded_frames = xp.transpose(encoded_frames, (0, 2, 1))
    overlap = _OVERLAP_FRAMES * hop_length
    chunks = []
    start = 0
    while start < total_frames:
        end = min(start + chunk_size, total_frames)
        out = body(encoded_frames[:, start:end, :])
        xp.eval(out)
        chunks.append(out)
        if end >= total_frames:
            break
        start = end - _OVERLAP_FRAMES
        xp.clear_cache()
    if len(chunks) == 1:
        return chunks[0]
    fade_in = xp.linspace(0.0, 1.0, overlap).reshape(1, -1, 1)
    fade_out = xp.linspace(1.0, 0.0, overlap).reshape(1, -1, 1)
    parts = []
    for index, chunk in enumerate(chunks):
        if index > 0:
            parts[-1] = parts[-1] + chunk[:, :overlap, :] * fade_in
        last = index == len(chunks) - 1
        head = 0 if index == 0 else overlap
        if last:
            parts.append(chunk[:, head:, :])
        else:
            parts.append(chunk[:, head:chunk.shape[1] - overlap, :])
            parts.append(chunk[:, chunk.shape[1] - overlap:, :] * fade_out)
    return xp.concatenate(parts, axis=1)


def compiled_decode(codec: Any, body: Callable[[Any], Any]) -> Callable[..., Any]:
    plain = codec.decode
    xp = _xp()

    def decode(encoded_frames: Any, chunk_size: int | None = None) -> Any:
        if chunk_size is None:
            return plain(encoded_frames, chunk_size=None)
        return decode_chunked(encoded_frames, chunk_size, body, codec.hop_length, xp)

    return decode


def _supported(codec: Any) -> bool:
    decoder = getattr(codec, "decoder", None)
    return all(callable(value) for value in (getattr(codec, "quantizer_out_proj", None), decoder,
                                              getattr(decoder, "snake_out", None), getattr(decoder, "conv_out", None))) \
        and isinstance(getattr(codec, "hop_length", None), int)


@contextmanager
def compile_decode(model: Any, _kwargs: dict[str, Any], context: dict[str, Any], *, patched: Patcher) -> Iterator[None]:
    codec = model.dacvae
    if not _supported(codec):
        context["cacheStats"]["compileDecode"] = "unsupported"
        yield
        return
    body = _COMPILED_BODIES.get(id(codec))
    if body is None:
        body = _COMPILED_BODIES[id(codec)] = _mx_compile(chunk_body(codec, _xp()))
    context["cacheStats"]["compileDecode"] = "compiled"
    with patched(codec, "decode", compiled_decode(codec, body)):
        yield

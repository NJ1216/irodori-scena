"""Long-lived JSON-lines worker for the pinned MLX Audio Irodori runtime."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

# The desktop sends SIGUSR1 on clicks, keys, and scrolling. Only the PyTorch
# worker implements the MPS idle lease; MLX must ignore this optional hint
# before loading the model, since SIGUSR1 otherwise terminates the process.
if hasattr(signal, "SIGUSR1"):
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server.mlx_acceleration_adapter import DEFAULT_FEATURES, run as run_acceleration
from server.scena_mlx_lora import AdapterSession, BASE_REPO, BASE_REVISION, RestorationError, verify_base_checkpoint, install_empty_caption_compatibility, verify_fp16_checkpoint, supports_lora_model

RESULT_PREFIX = "__SCENA_RESULT__"
MODEL_PATH = os.environ.get("IRODORI_TTS_MODEL_PATH", "")
VARIANT_ID = os.environ.get("IRODORI_TTS_VARIANT_ID", "mlx-fp16")
PRECISION = os.environ.get("IRODORI_TTS_PRECISION", "FP16")
CODEC_PRECISION: str | None = None
OPTIMIZATION_PROFILE = os.environ.get("IRODORI_TTS_OPTIMIZATION_PROFILE", "mlx-audio-0.5.0-fp16")
RUNTIME_ENGINE_ID = os.environ.get("IRODORI_TTS_RUNTIME_ENGINE_ID")


def emit(payload: dict[str, Any]) -> None:
    print(f"{RESULT_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)


def _load_model():
    if not MODEL_PATH or not Path(MODEL_PATH).is_dir():
        raise RuntimeError("SCENA must provide a complete local MLX model path.")
    if VARIANT_ID == "mlx-fp32":
        return _load_fp32_model()
    from mlx_audio.tts.utils import load_model

    if _supports_lora_runtime():
        verify_fp16_checkpoint(Path(MODEL_PATH) / "model.safetensors")
        config = json.loads((Path(MODEL_PATH) / "config.json").read_text(encoding="utf-8"))
        if config.get("quantization"):
            raise ValueError("LoRA cannot use a quantized model configuration.")
        model = load_model(MODEL_PATH)
        _finish_lora_model(model, expected_dtype="float16")
        return model
    return load_model(MODEL_PATH)


def _load_fp32_model():
    import mlx.core as mx
    from mlx_audio.tts.models.irodori_tts.config import ModelConfig
    from mlx_audio.tts.models.irodori_tts.irodori_tts import Model

    identity = (os.environ.get("IRODORI_TTS_BASE_REPO"), os.environ.get("IRODORI_TTS_BASE_REVISION"))
    if identity != (BASE_REPO, BASE_REVISION):
        raise ValueError("MLX FP32 requires the pinned official v4.1 Small base model.")
    checkpoint = Path(os.environ.get("IRODORI_TTS_FP32_CHECKPOINT", ""))
    verify_base_checkpoint(checkpoint)
    assets = Path(MODEL_PATH)
    config = json.loads((assets / "config.json").read_text(encoding="utf-8"))
    if config.get("quantization"):
        raise ValueError("MLX FP32 cannot use a quantized model configuration.")
    if not (assets / "dacvae" / "model.safetensors").is_file():
        raise ValueError("A complete local MLX Codec is required.")
    model = Model(ModelConfig.from_dict(config))
    weights = model.sanitize(mx.load(str(checkpoint)))
    if any(value.dtype != mx.float32 for value in weights.values()):
        raise ValueError("The official base checkpoint must contain only FP32 tensors.")
    model.load_weights(list(weights.items()), strict=True)
    mx.eval(model.parameters())
    Model.post_load_hook(model, assets)
    if model.dacvae is None:
        raise ValueError("The local MLX Codec could not be loaded.")
    _finish_lora_model(model, expected_dtype="float32")
    return model


def _worker_model_identity():
    origin_repo = os.environ.get("IRODORI_TTS_BASE_REPO")
    origin_revision = os.environ.get("IRODORI_TTS_BASE_REVISION")
    return {"baseModelRepo": origin_repo, "baseModelRevision": origin_revision,
            "repo": os.environ.get("IRODORI_TTS_ARTIFACT_REPO") or origin_repo,
            "revision": os.environ.get("IRODORI_TTS_ARTIFACT_REVISION") or origin_revision,
            "backend": "mlx", "variantId": VARIANT_ID, "precision": PRECISION}


def _supports_lora_runtime():
    return supports_lora_model(_worker_model_identity())


def _finish_lora_model(model, *, expected_dtype):
    global CODEC_PRECISION
    import mlx.core as mx
    from mlx.utils import tree_flatten

    base_parameters = dict(tree_flatten(model.model.parameters()))
    if len(base_parameters) != 714 or any(value.dtype != getattr(mx, expected_dtype) for value in base_parameters.values()):
        raise ValueError("The pinned base must have all 714 tensors in its selected precision.")
    codec_dtypes = {value.dtype for _, value in tree_flatten(model.dacvae.parameters())}
    CODEC_PRECISION = "fp32" if codec_dtypes == {mx.float32} else "fp16" if codec_dtypes == {mx.float16} else None
    install_empty_caption_compatibility(model, arrays=mx)
    model.eval()


def _execution(descriptor=None):
    return {"optimizationProfile": OPTIMIZATION_PROFILE, "variantId": VARIANT_ID,
            "backend": "mlx", "precision": PRECISION,
            "artifactRepo": _worker_model_identity()["repo"],
            "artifactRevision": _worker_model_identity()["revision"],
            "codec": {"repo": os.environ.get("IRODORI_TTS_CODEC_ARTIFACT_REPO"),
                      "revision": os.environ.get("IRODORI_TTS_CODEC_ARTIFACT_REVISION"),
                      "precision": CODEC_PRECISION} if _supports_lora_runtime() else None,
            "lora": {"applied": bool(descriptor), "adapterHash": descriptor.get("adapterHash") if descriptor else None,
                     "mix": {"baseWeight": descriptor["baseWeight"], "adapters": [{key: item.get(key) for key in ("adapterHash", "weight")} for item in descriptor["adapters"]]} if descriptor and "adapters" in descriptor else None,
                     "baseModelRepo": os.environ.get("IRODORI_TTS_BASE_REPO"),
                     "baseModelRevision": os.environ.get("IRODORI_TTS_BASE_REVISION"),
                     "artifactRepo": _worker_model_identity()["repo"],
                     "artifactRevision": _worker_model_identity()["revision"], "precision": PRECISION}}


def _write_wav(path: Path, audio: Any, sample_rate: int) -> str:
    import numpy as np
    from mlx_audio.audio_io import write

    # mlx-audio 0.5.0 scales only float32/64; passing Codec FP16 directly
    # truncates every normalized sample to zero when converting to PCM16.
    samples = np.asarray(audio, dtype=np.float32)
    if samples.size == 0 or not np.isfinite(samples).all():
        raise ValueError("Generated audio is empty or non-finite.")
    if not np.any(np.abs(samples) * 32767 >= 1):
        raise ValueError("Generated audio is silent at PCM16 precision.")
    path.parent.mkdir(parents=True, exist_ok=True)
    write(str(path), samples, sample_rate)
    return str(path)


def synthesize(model: Any, request: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    if request.get("operation") == "prepare":
        return [], _prewarm(model, request)
    descriptor = request.get("loraAdapter")
    if descriptor and not _supports_lora_runtime():
        raise ValueError("LoRA requires the pinned official MLX FP16 or FP32 configuration.")
    session = AdapterSession(model) if _supports_lora_runtime() else None
    scope = session.scoped(descriptor) if session else contextlib.nullcontext()
    with scope:
        return _generate(model, request, descriptor)


def _generation_kwargs(request: dict[str, Any], seed: int) -> dict[str, Any]:
    return {
        "text": str(request["text"]),
        "ref_audio": str(request.get("refWav") or "") or None,
        "instruct": str(request.get("caption") or "") or None,
        "num_steps": int(request["steps"]),
        "cfg_scale_text": float(request["textCfg"]),
        "cfg_scale_speaker": float(request["voiceCfg"]),
        "cfg_scale_caption": float(request["captionCfg"]),
        "t_schedule_mode": str(request["schedule"]),
        "sway_coeff": -1.0,
        "duration_scale": float(request["durationScale"]),
        "seconds": float(request["seconds"]) if request.get("seconds") is not None else None,
        "rng_seed": seed,
        "verbose": False,
    }


def _performance(acceleration: dict[str, Any]) -> dict[str, Any]:
    # The runtime identity (optimizationProfile) stays the pinned mlx-audio
    # profile; the SCENA adapter result is reported as performance data only.
    stats = {"accelerationProfile": acceleration.get("optimizationProfile"),
             "features": acceleration.get("features", []), **acceleration.get("cacheStats", {})}
    if "fallbackDetail" in acceleration:
        stats["fallbackDetail"] = acceleration["fallbackDetail"]
    return {"stageTimingsMs": acceleration.get("stageTimingsMs", {}),
            "fallbackReason": acceleration.get("fallbackReason"), "optimizationStats": stats}


# MeanFlow preparation requests carry no CFG or schedule; mlx-audio still needs values.
_PREPARE_DEFAULTS = {"textCfg": 3.0, "voiceCfg": 5.0, "captionCfg": 3.0, "schedule": "sway"}


def _prewarm(model: Any, request: dict[str, Any]) -> dict[str, Any]:
    """Run the short, unsaved preparation generation so the first real take skips GPU warm-up."""
    started = time.perf_counter()
    try:
        _result, acceleration = run_acceleration(model, _generation_kwargs({**_PREPARE_DEFAULTS, **request}, int(request.get("seed") or 0)),
                                                 runtime_version=RUNTIME_ENGINE_ID, features=DEFAULT_FEATURES, lora=False)
    except Exception as error:  # noqa: BLE001 - warm-up is best effort; generation reports real errors
        traceback.print_exc(file=sys.stderr)
        acceleration = {"fallbackReason": "prewarm-failed", "fallbackDetail": f"{type(error).__name__}: {error}"[-500:]}
    performance = _performance(acceleration)
    performance["stageTimingsMs"] = {**performance["stageTimingsMs"], "prewarmMs": round((time.perf_counter() - started) * 1000, 3)}
    return {**_execution(), **performance}


def _generate(model, request, descriptor):
    seed = int(request["seed"])
    count = int(request["numCandidates"])
    output = Path(str(request["output"]))
    outputs: list[str] = []
    acceleration: dict[str, Any] = {}
    for index in range(count):
        result, acceleration = run_acceleration(model, _generation_kwargs(request, seed + index), runtime_version=RUNTIME_ENGINE_ID,
                                                features=DEFAULT_FEATURES, lora=bool(descriptor))
        target = output if count == 1 else output.with_name(f"{output.stem}_{index + 1:03d}{output.suffix or '.wav'}")
        outputs.append(_write_wav(target, result.audio, int(result.sample_rate)))
    return outputs, {**_execution(descriptor), **_performance(acceleration), "seed": seed}


def main() -> None:
    model = _load_model()
    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
            with contextlib.redirect_stdout(sys.stderr):
                outputs, execution = synthesize(model, request)
            emit({"ok": True, "outputs": outputs, "prepared": request.get("operation") == "prepare", "execution": execution, "metrics": {}})
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            emit({"ok": False, "error": str(error)})
            if isinstance(error, RestorationError):
                raise SystemExit(1) from error


if __name__ == "__main__":
    main()

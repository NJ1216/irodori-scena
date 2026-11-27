"""Long-lived Irodori-TTS inference worker for irodori SCENA.

The official CLI creates an ``InferenceRuntime`` for every invocation.  This
small JSON-lines worker stays alive between requests, allowing the upstream
runtime cache to keep the model on the selected device.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import shutil
import signal
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

from irodori_acceleration_adapter import calibration_needed, clear_worker_caches, run as run_acceleration_adapter
from irodori_acceleration_sampler import note_ui_activity, wait_for_ui_idle
from irodori_cuda_calibration import CalibrationStore
from irodori_host import configure_audio_libraries, configure_cpu_threads, inference_device
from irodori_load_adapter import get_runtime as get_load_adapted_runtime
from irodori_runtime_layout import RuntimeCheckpoint, install_termination_cleanup, prepare_runtime_checkpoint


_AUDIO_DLL_DIRECTORIES = configure_audio_libraries()
RESULT_PREFIX = "__SCENA_RESULT__"
CHECKPOINT = os.environ.get("IRODORI_TTS_CHECKPOINT", "")
CODEC = os.environ.get("IRODORI_TTS_CODEC", "")
TOKENIZER = os.environ.get("IRODORI_TTS_TOKENIZER", "")
ENGINE_ROOT = Path(os.environ.get("IRODORI_TTS_ENGINE_DIR", ".")).resolve()
ENGINE_COMMIT = os.environ.get("IRODORI_TTS_ENGINE_COMMIT")
MODEL_IDENTITY = os.environ.get("IRODORI_TTS_MODEL_IDENTITY")
VARIANT_ID = os.environ.get("IRODORI_TTS_VARIANT_ID", "pytorch-fp32")
COMPUTE_PRECISION = os.environ.get("IRODORI_TTS_COMPUTE_PRECISION", "fp32")
_CALIBRATION_PATH = os.environ.get("IRODORI_TTS_CUDA_CALIBRATION")
CALIBRATION = CalibrationStore(Path(_CALIBRATION_PATH)) if _CALIBRATION_PATH else None
_RUNTIME_CHECKPOINT: RuntimeCheckpoint | None = None
_REFERENCE_PROBE: Path | None = None
_PROBE_PLACEHOLDER = "scena-calibration-reference"

install_termination_cleanup()
if hasattr(signal, "SIGUSR1"):
    signal.signal(signal.SIGUSR1, lambda _signal, _frame: note_ui_activity())

if not CHECKPOINT or not CODEC or not TOKENIZER:
    raise RuntimeError("SCENA must provide checkpoint, Codec, and tokenizer paths explicitly.")

# The worker is launched by the engine's uv environment, while this script
# lives in SCENA's repository.  Make the engine package importable explicitly.
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from irodori_tts.inference_runtime import (  # noqa: E402
    RuntimeKey,
    SamplingRequest,
    get_cached_runtime,
    resolve_cfg_scales,
    save_wav,
)


def emit(payload: dict[str, Any]) -> None:
    print(f"{RESULT_PREFIX}{json.dumps(payload, ensure_ascii=False)}", flush=True)


def mps_driver_memory() -> int | None:
    try:
        import torch

        return max(0, int(torch.mps.driver_allocated_memory()))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


def synthesize(request: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    global _RUNTIME_CHECKPOINT
    import torch

    device = inference_device(torch)
    configure_cpu_threads(torch, device)
    if device == "mps":
        wait_for_ui_idle(torch)
    checkpoint_path = Path(CHECKPOINT)
    tokenizer_path = Path(TOKENIZER)
    if not checkpoint_path.is_file() or not Path(CODEC).is_file() or not tokenizer_path.exists():
        raise FileNotFoundError("The selected local TTS runtime is incomplete.")
    if _RUNTIME_CHECKPOINT is None:
        _RUNTIME_CHECKPOINT = prepare_runtime_checkpoint(checkpoint_path, tokenizer_path)
    runtime_checkpoint = _RUNTIME_CHECKPOINT.path
    runtime_key = RuntimeKey(
        checkpoint=str(runtime_checkpoint),
        model_device=device,
        codec_repo=CODEC,
        model_precision=COMPUTE_PRECISION,
        codec_device=device,
        codec_precision="fp32",
        codec_deterministic_encode=True,
        codec_deterministic_decode=True,
        compile_model=False,
        compile_dynamic=False,
    )
    import irodori_tts.inference_runtime as upstream

    runtime, _ = get_load_adapted_runtime(
        upstream=upstream, torch=torch, get_cached=get_cached_runtime, key=runtime_key,
        engine_commit=ENGINE_COMMIT, model_identity=MODEL_IDENTITY, device=device,
    )

    caption = str(request.get("caption") or "").strip() or None
    ref_wav = str(request.get("refWav") or "").strip() or None
    if request.get("operation") == "calibrate" and request.get("referenceProbe"):
        ref_wav = _PROBE_PLACEHOLDER
    no_ref = ref_wav is None
    is_meanflow = getattr(runtime.model_cfg, "flow_parameterization", "rf_velocity") == "meanflow"
    sampling_kwargs = dict(
            text=str(request["text"]),
            caption=caption,
            ref_wav=ref_wav,
            no_ref=no_ref,
            ref_normalize_db=-16.0,
            ref_ensure_max=True,
            num_candidates=int(request["numCandidates"]),
            decode_mode="sequential",
            duration_scale=float(request["durationScale"]),
            seconds=float(request["seconds"]) if request.get("seconds") is not None else None,
            num_steps=int(request["steps"]),
            context_kv_cache=True,
            speaker_uncond_mode="mask",
            seed=int(request["seed"]),
            trim_tail=True,
            tail_window_size=20,
            tail_std_threshold=0.05,
            tail_mean_threshold=0.1,
    )
    if not is_meanflow:
        cfg_text, cfg_caption, cfg_speaker, _ = resolve_cfg_scales(
            cfg_guidance_mode="independent",
            cfg_scale_text=float(request["textCfg"]),
            cfg_scale_caption=float(request["captionCfg"]),
            cfg_scale_speaker=float(request["voiceCfg"]),
            cfg_scale=None,
            use_caption_condition=bool(runtime.model_cfg.use_caption_condition and caption),
            use_speaker_condition=bool(runtime.model_cfg.use_speaker_condition_resolved and not no_ref),
        )
        sampling_kwargs.update(
            cfg_scale_text=cfg_text, cfg_scale_caption=cfg_caption, cfg_scale_speaker=cfg_speaker,
            cfg_guidance_mode="independent", cfg_min_t=0.5, cfg_max_t=1.0,
            t_schedule_mode=str(request["schedule"]), sway_coeff=-1.0,
        )
    sampling_request = SamplingRequest(**sampling_kwargs)
    if request.get("operation") == "calibrate":
        needed = calibration_needed(runtime, sampling_request, engine_commit=ENGINE_COMMIT, model_identity=MODEL_IDENTITY,
                                    variant_id=VARIANT_ID, calibration=CALIBRATION)
        if not needed:
            return [], {"optimizationProfile": "not-run", "fallbackReason": "calibration-not-needed"}
        if sampling_request.ref_wav == _PROBE_PLACEHOLDER:
            sampling_request = dataclasses.replace(sampling_request, ref_wav=_reference_probe(runtime))
    result, execution = run_acceleration_adapter(
        runtime,
        sampling_request,
        engine_commit=ENGINE_COMMIT,
        model_identity=MODEL_IDENTITY,
        prepare=request.get("operation") == "prepare",
        variant_id=VARIANT_ID,
        calibration=CALIBRATION,
    )

    execution = {**execution, "variantId": VARIANT_ID, "precision": COMPUTE_PRECISION.upper()}
    if request.get("operation") in {"prepare", "calibrate"}:
        return [], execution
    wait_for_ui_idle(torch)
    output = Path(str(request["output"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    if int(request["numCandidates"]) == 1:
        return [str(save_wav(output, result.audio, result.sample_rate))], execution

    suffix = output.suffix or ".wav"
    return [
        str(save_wav(output.with_name(f"{output.stem}_{index:03d}{suffix}"), audio, result.sample_rate))
        for index, audio in enumerate(result.audios, start=1)
    ], execution


def _reference_probe(runtime: Any) -> str:
    """A short worker-made voice used only as calibration reference audio; deleted on exit."""
    global _REFERENCE_PROBE
    if _REFERENCE_PROBE is None or not _REFERENCE_PROBE.is_file():
        result = runtime.synthesize(SamplingRequest(text="参照音声の確認用です。", no_ref=True, num_steps=8, seed=0,
                                                    t_schedule_mode="sway"), log_fn=None)
        directory = Path(tempfile.mkdtemp(prefix="scena-calibration-"))
        _REFERENCE_PROBE = Path(str(save_wav(directory / "reference.wav", result.audio, result.sample_rate)))
    return str(_REFERENCE_PROBE)


def main() -> None:
    try:
        for raw_line in sys.stdin:
            try:
                request = json.loads(raw_line)
                # Keep upstream diagnostics out of the JSON response stream.
                with contextlib.redirect_stdout(sys.stderr):
                    outputs, execution = synthesize(request)
                emit({"ok": True, "outputs": outputs, "prepared": request.get("operation") == "prepare", "execution": execution, "metrics": {"mpsDriverAllocatedBytes": mps_driver_memory()}})
            except Exception as error:  # Keep this worker alive after a bad request.
                traceback.print_exc(file=sys.stderr)
                emit({"ok": False, "error": str(error)})
    finally:
        clear_worker_caches()
        if _REFERENCE_PROBE is not None:
            shutil.rmtree(_REFERENCE_PROBE.parent, ignore_errors=True)
        if _RUNTIME_CHECKPOINT is not None:
            _RUNTIME_CHECKPOINT.cleanup()


if __name__ == "__main__":
    main()

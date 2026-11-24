from __future__ import annotations

from contextlib import nullcontext
from server.scena_mlx_lora import supports_lora_model
from server.file_lock import lock_exclusive, unlock
import signal
import sys

import psutil

from server.app_deps import (
    atexit,
    os,
    shutil,
    subprocess,
    threading,
    Path,
    Any,
    Callable,
    HTTPException,
)
from server.registry import deps
from server.modules.llm_runtime_binding import LOCK as RUNTIME_SERIALIZATION, serialized
from server.modules.worker_exchange import generation_response, preparation_response

INFERENCE_SYNTHESIS_LOCK = threading.Lock()
INFERENCE_METAL_BYTES: int | None = None
INFERENCE_WORKER_FAILED = False
_INFERENCE_THREAD_EXECUTION = threading.local()
LAST_INFERENCE_EXECUTION: dict[str, Any] = {"optimizationProfile": "upstream-eager"}


def _runtime_serialization():
    """Keep Windows runtimes exclusive without stalling macOS API reads."""
    return RUNTIME_SERIALIZATION if sys.platform == "win32" else nullcontext()


def _observed_engine_commit(runtime: dict[str, Any], engine: Path) -> str:
    configured = str(runtime["engine"].get("commit") or "")
    if runtime["engine"].get("source") != "external-library":
        return configured
    try:
        observed = subprocess.check_output(
            ["git", "-C", str(engine), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    return observed if len(observed) == 40 and all(char in "0123456789abcdef" for char in observed) else ""


def _model_tokenizer_path(model: dict[str, Any]) -> Path:
    configured = str(model.get("tokenizerPath") or "").strip()
    if configured:
        return Path(configured)
    return Path(str(model["path"])) / "tokenizer"


def engine_dir() -> Path:
    runtime = deps.selected_tts_runtime()
    if runtime is None or runtime.get("model") is None:
        raise HTTPException(status_code=409, detail="このプロジェクトで使用する音声モデルが見つかりません。音声モデルを選択または追加してください。")
    if runtime["model"].get("backend") == "mlx":
        return deps.PROJECT_ROOT
    configured = runtime["engine"].get("path")
    path = Path(str(configured)).expanduser()
    resolved = path.resolve()
    if not (resolved / "infer.py").is_file():
        raise HTTPException(
            status_code=503,
            detail="Irodori-TTS was not found. Set IRODORI_TTS_ENGINE_DIR or place the engine at ../_ExternalRepos/Irodori-TTS.",
        )
    return resolved


def stop_inference_worker_locked() -> None:
    """Stop the worker while ``INFERENCE_WORKER_LOCK`` is held."""
    global INFERENCE_METAL_BYTES, INFERENCE_WORKER_FAILED
    worker = deps.INFERENCE_WORKER
    generation = deps.memory_generation("tts")
    INFERENCE_WORKER_FAILED = worker is not None
    if worker is not None and worker.poll() is None:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait(timeout=5)
    # A failed stop keeps its process and ownership visible for a later retry.
    if deps.INFERENCE_WORKER is worker:
        deps.INFERENCE_WORKER = None
        INFERENCE_METAL_BYTES = None
        INFERENCE_WORKER_FAILED = False
        deps.release_memory("tts", generation=generation)


@serialized
def shutdown_inference_worker() -> None:
    with deps.INFERENCE_WORKER_LOCK:
        stop_inference_worker_locked()


def tts_metal_memory() -> int | None:
    worker = deps.INFERENCE_WORKER
    if worker is None or worker.poll() is not None:
        return 0
    return INFERENCE_METAL_BYTES


def _record_inference_metal(metric: object) -> None:
    global INFERENCE_METAL_BYTES
    if isinstance(metric, int) and not isinstance(metric, bool):
        INFERENCE_METAL_BYTES = max(0, metric)


atexit.register(shutdown_inference_worker)


@deps.app.post("/api/inference/interaction-lease")
def interaction_lease() -> dict[str, bool]:
    deps.note_tts_interaction()
    worker = deps.INFERENCE_WORKER
    if worker is not None and worker.poll() is None and hasattr(signal, "SIGUSR1"):
        try:
            os.kill(worker.pid, signal.SIGUSR1)
        except ProcessLookupError:
            pass
    return {"ok": True}


def inference_worker_locked(engine: Path) -> subprocess.Popen[str]:
    """Return a live persistent inference process while its lock is held."""
    global INFERENCE_METAL_BYTES
    if INFERENCE_WORKER_FAILED:
        stop_inference_worker_locked()
    if deps.INFERENCE_WORKER is not None and deps.INFERENCE_WORKER.poll() is None:
        return deps.INFERENCE_WORKER
    deps.INFERENCE_WORKER = None
    runtime = deps.selected_tts_runtime()
    if runtime is None or runtime.get("model") is None:
        raise HTTPException(status_code=409, detail="このプロジェクトで使用する音声モデルが見つかりません。")
    model = runtime["model"]
    mlx = model.get("backend") == "mlx"
    worker_script = deps.PROJECT_ROOT / "server" / ("mlx_irodori_worker.py" if mlx else "irodori_worker.py")
    python = runtime["engine"].get("pythonPath")
    if not python:
        raise HTTPException(status_code=409, detail="選択中の音声モデルに対応するPython環境がありません。")
    command = [str(python), str(worker_script)]
    worker_env = {**os.environ, "IRODORI_TTS_ENGINE_DIR": str(engine), "PYTHONIOENCODING": "utf-8"}
    if mlx:
        model_root = Path(str(model.get("mlxAssetsPath") or model["path"]))
        required = (model_root / "model.safetensors", model_root / "dacvae" / "model.safetensors", model_root / "tokenizer")
        if not all(path.exists() for path in required):
            raise HTTPException(status_code=409, detail="選択中のMLXモデルに必要な資産が揃っていません。")
        worker_env.update(IRODORI_TTS_MODEL_PATH=str(model_root),
                          IRODORI_TTS_BASE_REPO=str(model.get("baseModelRepo") or model.get("repo") or ""),
                          IRODORI_TTS_BASE_REVISION=str(model.get("baseModelRevision") or model.get("revision") or ""),
                          IRODORI_TTS_ARTIFACT_REPO=str(model.get("repo") or ""),
                          IRODORI_TTS_ARTIFACT_REVISION=str(model.get("revision") or ""))
        if supports_lora_model(model) and model.get("variantId") == "mlx-fp16":
            worker_env.update(IRODORI_TTS_CODEC_ARTIFACT_REPO=str(model.get("repo") or ""),
                              IRODORI_TTS_CODEC_ARTIFACT_REVISION=str(model.get("revision") or ""))
        if model.get("variantId") == "mlx-fp32":
            worker_env["IRODORI_TTS_FP32_CHECKPOINT"] = str(Path(str(model["path"])) / "model.safetensors")
            worker_env.update(IRODORI_TTS_CODEC_ARTIFACT_REPO=str(model.get("mlxAssetsRepo") or ""),
                              IRODORI_TTS_CODEC_ARTIFACT_REVISION=str(model.get("mlxAssetsRevision") or ""))
        worker_env.update(IRODORI_TTS_VARIANT_ID=str(model.get("variantId")), IRODORI_TTS_PRECISION=str(model.get("precision")), IRODORI_TTS_OPTIMIZATION_PROFILE=str(model.get("optimizationProfile")),
                          IRODORI_TTS_RUNTIME_ENGINE_ID=str(runtime["engine"].get("id") or ""))
    else:
        worker_env.update(IRODORI_TTS_ENGINE_DIR=str(engine))
    checkpoint = Path(str(model["path"])) / str(model.get("checkpointFile") or "model.safetensors")
    codec = Path(str(model["codecPath"]))
    codec = codec / "weights.pth" if codec.is_dir() else codec
    tokenizer = _model_tokenizer_path(model)
    if not mlx and (not checkpoint.is_file() or not codec.is_file() or not tokenizer.exists()):
        raise HTTPException(status_code=409, detail="選択中の音声モデルに必要なmodel、Codec、tokenizerが揃っていません。")
    if not mlx:
        worker_env.update(IRODORI_TTS_CHECKPOINT=str(checkpoint), IRODORI_TTS_CODEC=str(codec),
                      IRODORI_TTS_TOKENIZER=str(tokenizer),
                      IRODORI_TTS_ENGINE_COMMIT=_observed_engine_commit(runtime, engine),
                      IRODORI_TTS_MODEL_IDENTITY=f"{model.get('repo')}@{model.get('revision')}",
                      IRODORI_TTS_VARIANT_ID=str(model.get("variantId") or "pytorch-fp32"),
                      IRODORI_TTS_COMPUTE_PRECISION=str(model.get("computePrecision") or "fp32"))
        worker_env["IRODORI_TTS_CUDA_CALIBRATION"] = str(deps.DATA_ROOT / "tts" / "cuda-acceleration-calibration.json")
        if cores := psutil.cpu_count(logical=False):
            worker_env["IRODORI_TTS_CPU_THREADS"] = str(cores)
    try:
        deps.INFERENCE_WORKER = subprocess.Popen(
            command,
            cwd=engine,
            env=worker_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
    except OSError as error:
        raise HTTPException(status_code=500, detail="Irodori-TTS worker could not be started.") from error
    INFERENCE_METAL_BYTES = 0
    return deps.INFERENCE_WORKER


def runtime_serialization():
    return _runtime_serialization()


def exchange_worker_request(worker, request):
    return _exchange_response(worker, request)


def _exchange_response(worker, request, should_cancel=None):
    global INFERENCE_WORKER_FAILED
    try:
        if request["operation"] == "prepare":
            return preparation_response(worker, request)
        return generation_response(worker, request, should_cancel)
    except Exception:
        INFERENCE_WORKER_FAILED = True
        try:
            stop_inference_worker_locked()
        except Exception:
            # Worker cleanup is best effort. Preserve the exchange failure—most
            # importantly GenerationCancelled—so the route can return its
            # expected interruption response instead of a misleading 500.
            pass
        raise


def synthesis_request(
    *,
    text: str,
    caption: str | None,
    output: str | None,
    seed: int,
    ref_wav: str | None,
    quality: str,
    generation_settings: dict[str, Any] | None,
    num_candidates: int,
    lora_adapter: dict[str, Any] | None,
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Build the worker request; quality decides steps and schedule for every caller."""
    generation_settings = generation_settings or {}
    is_meanflow = capabilities.get("flowParameterization") == "meanflow"
    default_steps = 40 if quality == "quality" else 8 if quality == "turbo" else 16
    steps = int(capabilities.get("fixedSteps") or generation_settings.get("steps", default_steps))
    speech_rate = float(generation_settings.get("speechRate", 1.2))
    duration_scale = round(1 / max(0.5, min(2.0, speech_rate)), 4)
    seconds = deps.normalize_target_duration(generation_settings.get("targetDurationSeconds"))
    request = {
        "operation": "synthesize",
        "text": text,
        "caption": caption,
        "output": output,
        "seed": seed,
        "refWav": ref_wav,
        "steps": steps,
        "durationScale": duration_scale,
        "seconds": seconds,
        "numCandidates": num_candidates,
        "loraAdapter": lora_adapter,
    }
    if not is_meanflow:
        request.update({
            "textCfg": float(generation_settings.get("textCfg", 3.0)),
            "voiceCfg": float(generation_settings.get("voiceCfg", 5.0)),
            "captionCfg": float(generation_settings.get("captionCfg", 3.0)),
            "schedule": "linear" if quality == "quality" else "sway",
        })
    return request


def _run_irodori(
    *,
    text: str,
    caption: str | None,
    output: Path,
    seed: int,
    ref_wav: Path | None,
    quality: str,
    generation_settings: dict[str, Any] | None = None,
    num_candidates: int = 1,
    lora_adapter: dict[str, Any] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[Path]:
    global INFERENCE_METAL_BYTES, LAST_INFERENCE_EXECUTION
    engine = engine_dir()
    if lora_adapter:
        runtime_model = (deps.selected_tts_runtime() or {}).get("model") or {}
        supported = supports_lora_model(runtime_model)
        if not supported:
            raise HTTPException(status_code=409, detail="LoRAは公式v4.1 Smallの固定MLX FP16／FP32構成で利用できます。音声モデル設定で選択してください。")
    output.parent.mkdir(parents=True, exist_ok=True)
    request = synthesis_request(
        text=text, caption=caption, output=str(output), seed=seed, ref_wav=str(ref_wav) if ref_wav else None,
        quality=quality, generation_settings=generation_settings, num_candidates=num_candidates,
        lora_adapter=lora_adapter, capabilities=deps.selected_model_capabilities() or {},
    )
    with deps.INFERENCE_WORKER_LOCK:
        worker = inference_worker_locked(engine)
        deps.set_worker_background(worker, False)  # a load or calibration may have started this worker
        response = _exchange_response(worker, request, should_cancel)
        metric = (response.get("metrics") or {}).get("mpsDriverAllocatedBytes")
        _record_inference_metal(metric)
        execution = response.get("execution")
        LAST_INFERENCE_EXECUTION = dict(execution) if isinstance(execution, dict) else {"optimizationProfile": "upstream-eager", "fallbackReason": "missing-worker-metadata"}
        runtime_model = (deps.selected_tts_runtime() or {}).get("model", {})
        LAST_INFERENCE_EXECUTION.update({
            "variantId": runtime_model.get("variantId", "pytorch-fp32"),
            "backend": runtime_model.get("backend", "pytorch"),
            "artifactRepo": runtime_model.get("repo"),
            "artifactRevision": runtime_model.get("revision"),
            "precision": runtime_model.get("precision", LAST_INFERENCE_EXECUTION.get("precision", "FP32")),
        })
        _INFERENCE_THREAD_EXECUTION.value = dict(LAST_INFERENCE_EXECUTION)
        outputs = [Path(item) for item in response.get("outputs", [])]
        if len(outputs) != num_candidates or not all((path.is_file() for path in outputs)):
            raise HTTPException(status_code=500, detail="Irodori-TTS did not produce the expected WAV files.")
        return outputs


def prepare_irodori_worker(*, coexist: bool = False) -> None:
    """Load all selected assets and run one short, unsaved MPS inference."""
    with _runtime_serialization():
        deps.acquire_tts_memory("Irodori-TTS準備", coexist=coexist)
        engine = engine_dir()
        capabilities = deps.selected_model_capabilities() or {}
        is_meanflow = capabilities.get("flowParameterization") == "meanflow"
        request = {
            "operation": "prepare", "text": "準備します。", "caption": None, "output": None,
            "seed": 0, "refWav": None, "steps": int(capabilities.get("fixedSteps") or 1),
            "durationScale": 1.0, "numCandidates": 1,
        }
        if not is_meanflow:
            request.update({"textCfg": 3.0, "voiceCfg": 5.0, "captionCfg": 3.0, "schedule": "sway"})
        with deps.INFERENCE_WORKER_LOCK:
            worker = inference_worker_locked(engine)
            deps.set_worker_background(worker, True)
            response = _exchange_response(worker, request)
            metric = (response.get("metrics") or {}).get("mpsDriverAllocatedBytes")
            _record_inference_metal(metric)


def last_inference_execution() -> dict[str, Any]:
    return dict(getattr(_INFERENCE_THREAD_EXECUTION, "value", {"optimizationProfile": "upstream-eager"}))


def run_irodori(
    *,
    text: str,
    caption: str | None,
    output: Path,
    seed: int,
    ref_wav: Path | None,
    quality: str,
    generation_settings: dict[str, Any] | None = None,
    num_candidates: int = 1,
    lora_adapter: dict[str, Any] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[Path]:
    """Run exactly one Irodori-TTS synthesis at a time; never queue a second one."""
    if not INFERENCE_SYNTHESIS_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail={
            "code": "operation_conflict",
            "message": "Irodori-TTSの音声合成を実行中です。完了または停止後に再試行してください。",
        })
    try:
        deps.set_worker_background(deps.INFERENCE_WORKER, False)  # before waiting for a background load
        with _runtime_serialization():
            return _run_with_memory(text=text, caption=caption, output=output, seed=seed, ref_wav=ref_wav,
                                    quality=quality, generation_settings=generation_settings,
                                    num_candidates=num_candidates, lora_adapter=lora_adapter, should_cancel=should_cancel)
    finally:
        INFERENCE_SYNTHESIS_LOCK.release()


def _run_with_memory(**kwargs) -> list[Path]:
    lock_file = None
    locked = False
    try:
        deps.acquire_tts_memory("Irodori-TTS音声生成")
        model_id = (deps.selected_tts_runtime() or {}).get("model", {}).get("id")
        deps.mark_tts_in_use(model_id)
        lock_path = deps.MEDIA_ROOT / ".irodori-synthesis.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("a+")
        try:
            lock_exclusive(lock_file)
            locked = True
        except BlockingIOError as error:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "operation_conflict",
                    "message": "別のアプリプロセスでIrodori-TTSの音声合成を実行中です。",
                },
            ) from error
        return _run_irodori(**kwargs)
    finally:
        if lock_file is not None:
            if locked:
                unlock(lock_file)
            lock_file.close()
        worker = deps.INFERENCE_WORKER
        if worker is None or worker.poll() is not None:
            deps.release_memory("tts")
        elif not INFERENCE_WORKER_FAILED:
            deps.mark_tts_ready((deps.selected_tts_runtime() or {}).get("model", {}).get("id"))


def find_character(project: dict[str, Any], character_id: str) -> dict[str, Any]:
    for character in project.get("characters", []):
        if character.get("id") == character_id:
            return character
    raise HTTPException(status_code=404, detail="Character not found.")


def find_line(project: dict[str, Any], line_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []):
            if line.get("id") == line_id:
                return (scene, line)
    raise HTTPException(status_code=404, detail="Dialogue line not found.")


def remove_line_takes(line_id: str) -> None:
    takes_root = (deps.MEDIA_ROOT / "takes").resolve()
    take_dir = (takes_root / deps.safe_segment(line_id)).resolve()
    try:
        take_dir.relative_to(takes_root)
    except ValueError as error:
        raise HTTPException(status_code=500, detail="Dialogue take directory was invalid.") from error
    if take_dir.exists():
        shutil.rmtree(take_dir)


def archive_line_takes(line: dict[str, Any]) -> None:
    """Keep old WAV references but make them unavailable after a voice change."""
    takes = line.get("takes", [])
    if takes:
        line["archivedTakes"] = line.get("archivedTakes", []) + takes
    line["takes"] = []
    line["selectedTakeId"] = None


def clear_voice_candidates(project: dict[str, Any]) -> None:
    candidates_root = (deps.MEDIA_ROOT / "candidates").resolve()
    for candidate in project.get("candidates", []):
        source = Path(str(candidate.get("file", ""))).resolve()
        try:
            source.relative_to(candidates_root)
        except ValueError:
            continue
        if source.is_file():
            source.unlink()
    project["candidates"] = []


deps.register(
    __name__,
    [
        "archive_line_takes",
        "clear_voice_candidates",
        "engine_dir",
        "find_character",
        "find_line",
        "exchange_worker_request",
        "inference_worker_locked",
        "INFERENCE_SYNTHESIS_LOCK",
        "runtime_serialization",
        "synthesis_request",
        "remove_line_takes",
        "run_irodori",
        "last_inference_execution",
        "prepare_irodori_worker",
        "interaction_lease",
        "shutdown_inference_worker",
        "tts_metal_memory",
        "stop_inference_worker_locked",
    ],
)

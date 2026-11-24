from __future__ import annotations

import hashlib
import os
import shutil
from server import subprocess_boundary as subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi

from server.app_deps import HTTPException
from server.modules.huggingface_models import _download_file, _model_info_with_optional_token
from server.modules.tts_environment_commands import inference_install_options, run_environment_command
from server.modules.tts_install_placement import (
    engine_environment_path,
    is_windows,
    place_windows_directory,
    rollback_windows_engine,
    validate_engine_source,
    validate_environment,
)
from server.platform_support import environment_python
from server.modules.tts_mlx_variants import mlx_engine_id, mlx_runtime
from server.registry import deps

TTS_JOBS: dict[str, dict[str, Any]] = {}
TTS_CANCEL: dict[str, threading.Event] = {}
TTS_JOB_LOCK = threading.RLock()
ACTIVE_TTS_JOB: str | None = None
CHUNK_BYTES = 1024 * 1024


def _job(asset_kind: str, asset_id: str) -> tuple[dict[str, Any], threading.Event]:
    global ACTIVE_TTS_JOB
    with TTS_JOB_LOCK:
        if ACTIVE_TTS_JOB and TTS_JOBS[ACTIVE_TTS_JOB]["state"] not in {"complete", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="TTS資産の導入は同時に1件だけ実行できます。")
        job_id = f"tts_{uuid.uuid4().hex[:16]}"
        state = {"id": job_id, "assetKind": asset_kind, "assetId": asset_id, "state": "queued",
                 "stage": "queued", "downloadedBytes": 0, "totalBytes": 0, "currentFile": None,
                 "error": None, "errorCategory": None}
        cancel = threading.Event()
        TTS_JOBS[job_id], TTS_CANCEL[job_id], ACTIVE_TTS_JOB = state, cancel, job_id
        return state, cancel


def _catalog_item(kind: str, asset_id: str) -> dict[str, Any]:
    items = deps.tts_catalog()["engines" if kind == "engine" else "models"]
    item = next((entry for entry in items if entry["id"] == asset_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="互換カタログに資産がありません。")
    if not item.get("installable"):
        raise HTTPException(status_code=409, detail=str(item.get("unavailableReason") or "この資産は追加できません。"))
    return item


def _catalog_variant(model_id: str, variant_id: str) -> dict[str, Any]:
    model = _catalog_item("model", model_id)
    variant = next((item for item in model.get("variants", []) if item.get("id") == variant_id), None)
    if variant is None:
        raise HTTPException(status_code=404, detail="互換カタログにバリアントがありません。")
    if not variant.get("available", True):
        raise HTTPException(status_code=409, detail=str(variant.get("unavailableReason") or "この環境では利用できません。"))
    return {**model, **variant, "id": f"{model_id}::{variant_id}", "baseModelId": model_id, "variantId": variant_id,
            "baseRepo": model["repo"], "baseRevision": model["revision"], "baseDisplayName": model["displayName"]}


def _safe_extract(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        roots = {Path(member.name).parts[0] for member in members if Path(member.name).parts}
        if len(roots) != 1:
            raise ValueError("エンジンarchiveのルートが一つではありません。")
        for member in members:
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts or member.issym() or member.islnk():
                raise ValueError("エンジンarchiveに安全でないパスがあります。")
            resolved = (destination / relative).resolve()
            resolved.relative_to(destination.resolve())
        bundle.extractall(destination, filter="data")
    return destination / next(iter(roots))


def _download_url(url: str, destination: Path, state: dict[str, Any], cancel: threading.Event) -> None:
    if destination.is_file():
        state.update(downloadedBytes=destination.stat().st_size, totalBytes=destination.stat().st_size, stage="downloaded")
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        total = int(response.headers.get("Content-Length", "0")) + offset
        state.update(totalBytes=total, downloadedBytes=offset, stage="downloading")
        if offset and getattr(response, "status", 200) != 206:
            offset = 0
            state.update(totalBytes=int(response.headers.get("Content-Length", "0")), downloadedBytes=0)
        with partial.open("ab" if offset else "wb") as output:
            while chunk := response.read(CHUNK_BYTES):
                if cancel.is_set():
                    raise InterruptedError
                output.write(chunk)
                state["downloadedBytes"] += len(chunk)
    partial.replace(destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _uv_binary() -> str:
    configured = os.environ.get("SCENA_UV_EXECUTABLE", "")
    candidates = [Path(configured)] if configured else []
    executable = Path(sys.executable).resolve()
    uv_name = "uv.exe" if sys.platform == "win32" else "uv"
    candidates.extend((executable.parent / "environment-manager" / uv_name, executable.parent.parent / "Resources/environment-manager" / uv_name))
    found = shutil.which("uv")
    if found:
        candidates.append(Path(found))
    binary = next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)
    if binary is None:
        raise OSError("SCENA環境管理ツールが見つかりません。アプリを再インストールしてください。")
    return str(binary)


def _engine_venv_command(uv: str, item: dict[str, Any], environment: Path, platform: str | None = None) -> list[str]:
    windows_options = ["--no-project", "--clear", "--force"] if is_windows(platform) else []
    return [uv, "venv", *windows_options, "--python", item["pythonVersion"], str(environment)]


def _install_engine(item: dict[str, Any], state: dict[str, Any], cancel: threading.Event) -> None:
    staging = deps.TTS_DOWNLOADS_ROOT / f"engine-{item['commit']}"
    archive = staging / "engine.tar.gz"
    extracted = staging / "source"
    staged_environment = staging / "environment"
    engine_target = deps.TTS_ENGINES_ROOT / item["commit"]
    env_target = deps.TTS_ENVIRONMENTS_ROOT / item["commit"]
    windows = is_windows()
    environment = engine_environment_path(staged_environment, env_target)
    staging.mkdir(parents=True, exist_ok=True)
    state["currentFile"] = "Irodori-TTS source"
    _download_url(item["archiveUrl"], archive, state, cancel)
    state["stage"] = "verifying"
    if _sha256(archive) != item["archiveSha256"]:
        archive.unlink(missing_ok=True)
        raise ValueError("エンジンarchiveのSHA-256が一致しません。")
    shutil.rmtree(extracted, ignore_errors=True)
    source = _safe_extract(archive, extracted)
    validate_engine_source(source, item["dependencyLockSha256"], _sha256)
    if cancel.is_set():
        raise InterruptedError
    state.update(stage="environment", currentFile="Python 3.10 / inference dependencies")
    if shutil.disk_usage(staging).free < 10 * 1024**3:
        raise OSError("Python環境を構築する空き容量が不足しています。")
    uv = _uv_binary()
    run_environment_command(_engine_venv_command(uv, item, environment), timeout=600, cancel=cancel)
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(environment)}
    options, profile = inference_install_options()
    run_environment_command([uv, "sync", "--frozen", "--no-dev", *options, "--project", str(source)], timeout=3600, env=env, cancel=cancel)
    if cancel.is_set():
        raise InterruptedError
    validate_environment(environment)
    if windows:
        place_windows_directory(
            source,
            engine_target,
            lambda path: validate_engine_source(path, item["dependencyLockSha256"], _sha256),
        )
    else:
        source.replace(engine_target)
        environment.replace(env_target)
    registry = deps.read_tts_registry()
    registry["engines"].append({
        "id": item["id"], "displayName": item["displayName"], "source": "managed", "repo": item["repo"],
        "commit": item["commit"], "path": str(engine_target), "pythonPath": str(environment_python(env_target)),
        "diskBytes": _tree_bytes(engine_target) + _tree_bytes(env_target), "verification": "verified",
        "optimizationProfile": profile or item["optimizationProfile"], "license": item["license"],
        "licenseUrl": item["licenseUrl"], "installedAt": int(time.time()),
    })
    if not registry.get("defaultEngineId"):
        registry["defaultEngineId"] = item["id"]
    try:
        deps.write_tts_registry(registry)
    except BaseException:
        if windows:
            try:
                rollback_windows_engine(engine_target, env_target)
            except OSError:
                pass
        raise
    shutil.rmtree(staging, ignore_errors=True)


def _tree_bytes(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _download_hf_repo(
    repo: str,
    revision: str,
    target: Path,
    state: dict[str, Any],
    cancel: threading.Event,
    allowed_files: list[str] | None = None,
) -> None:
    info, token = _model_info_with_optional_token(HfApi(token=False), repo, revision=revision, files_metadata=True)
    if info.sha != revision:
        raise ValueError("Hugging Face revisionが一致しません。")
    requested = set(allowed_files) if allowed_files is not None else None
    files = []
    for entry in info.siblings or []:
        name = entry.rfilename
        if not name or name.startswith(".git/") or requested is not None and name not in requested:
            continue
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Hugging Face資産に安全でないパスがあります。")
        files.append(entry)
    if requested is not None and {entry.rfilename for entry in files} != requested:
        raise ValueError("モデルの許可済み取得対象が不足しています。")
    repo_total = sum(int(entry.size or 0) for entry in files)
    state["totalBytes"] += repo_total
    target.mkdir(parents=True, exist_ok=True)
    existing = sum((target / entry.rfilename).stat().st_size for entry in files if (target / entry.rfilename).is_file())
    if shutil.disk_usage(target).free < max(0, repo_total - existing) + 2 * 1024**3:
        raise OSError("TTS資産を導入する空き容量が不足しています。")
    for entry in files:
        if cancel.is_set():
            raise InterruptedError
        state.update(stage="downloading", currentFile=entry.rfilename)
        destination = target / entry.rfilename
        if destination.is_file() and (not entry.size or destination.stat().st_size == int(entry.size)):
            state["downloadedBytes"] += destination.stat().st_size
            continue
        _download_file(repo, entry.rfilename, revision, target, state, cancel, token, int(entry.size or 0))


def _download_legacy_tokenizer(item: dict[str, Any], model: Path, state: dict[str, Any], cancel: threading.Event) -> None:
    if (model / "tokenizer").is_dir():
        return
    repo, revision = item.get("tokenizerRepo"), item.get("tokenizerRevision")
    if not repo or repo == item["repo"]:
        return
    info, token = _model_info_with_optional_token(HfApi(token=False), repo, revision=revision, files_metadata=True)
    if info.sha != revision:
        raise ValueError("tokenizer revisionが一致しません。")
    target = model / "tokenizer"
    target.mkdir(parents=True, exist_ok=True)
    for entry in info.siblings or []:
        if entry.rfilename not in {"tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"}:
            continue
        if cancel.is_set():
            raise InterruptedError
        state.update(stage="downloading", currentFile=f"tokenizer/{entry.rfilename}")
        _download_file(repo, entry.rfilename, revision, target, state, cancel, token, int(entry.size or 0))
    tokenizer_json = target / "tokenizer.json"
    expected = item.get("tokenizerSha256")
    if expected and (not tokenizer_json.is_file() or _sha256(tokenizer_json) != expected):
        tokenizer_json.unlink(missing_ok=True)
        raise ValueError("tokenizerのSHA-256が一致しません。")


def _ensure_mlx_environment(state: dict[str, Any], cancel: threading.Event, item: dict[str, Any] | None = None) -> Path:
    runtime = mlx_runtime(item or {})
    environment = deps.TTS_ENVIRONMENTS_ROOT / f"mlx-audio-{runtime['version']}"
    python = environment_python(environment)
    if python.is_file():
        return python
    staging = deps.TTS_DOWNLOADS_ROOT / f"mlx-audio-{runtime['version']}-environment"
    shutil.rmtree(staging, ignore_errors=True)
    state.update(stage="environment", currentFile=f"mlx-audio {runtime['version']}")
    uv = _uv_binary()
    run_environment_command([uv, "venv", "--python", "3.10", str(staging)], timeout=600, cancel=cancel)
    if cancel.is_set():
        raise InterruptedError
    staged_python = environment_python(staging)
    run_environment_command([uv, "pip", "install", "--python", str(staged_python), runtime["package"]], timeout=3600, cancel=cancel)
    if cancel.is_set():
        raise InterruptedError
    staging.replace(environment)
    return environment_python(environment)


def _publish_model_directory(model: Path, target: Path) -> None:
    """Atomically publish a first variant, then merge later shared-revision files."""
    if not target.exists():
        model.replace(target)
        return
    for source in model.rglob("*"):
        if source.is_file():
            destination = target / source.relative_to(model)
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.replace(destination)


def _install_model(item: dict[str, Any], state: dict[str, Any], cancel: threading.Event) -> None:
    staging = deps.TTS_DOWNLOADS_ROOT / f"model-{item['revision']}"
    model = staging / "model"
    codec = staging / "codec"
    model_target = deps.TTS_MODELS_ROOT / item["revision"]
    codec_target = deps.TTS_CODECS_ROOT / item["codecRevision"]
    for relative in ("README.md", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json"):
        shared = model_target / relative
        if shared.is_file() and relative in (item.get("downloadFiles") or []):
            destination = model / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(shared, destination)
    auxiliary = item.get("auxiliaryAssets") or {}
    allowed = item.get("downloadFiles")
    primary_files = [path for path in allowed if path not in auxiliary.get("downloadFiles", [])] if allowed else None
    _download_hf_repo(item["repo"], item["revision"], model, state, cancel, primary_files)
    if auxiliary:
        _download_hf_repo(auxiliary["repo"], auxiliary["revision"], model, state, cancel, auxiliary["downloadFiles"])
    _download_legacy_tokenizer(item, model, state, cancel)
    mlx = item.get("backend") == "mlx"
    mlx_python = _ensure_mlx_environment(state, cancel, item) if mlx else None
    if not mlx and not (codec_target / "weights.pth").is_file():
        _download_hf_repo(item["codecRepo"], item["codecRevision"], codec, state, cancel)
    codec_file = model / "dacvae" / "model.safetensors" if mlx else (codec_target / "weights.pth" if codec_target.exists() else codec / "weights.pth")
    checkpoint_file = str(item.get("checkpointFile") or "model.safetensors")
    if not (model / checkpoint_file).is_file() or not (model / "tokenizer").is_dir() or not codec_file.is_file():
        raise ValueError("モデル、tokenizer、Codecの必須資産が不足しています。")
    state["stage"] = "verifying"
    model_valid = _sha256(model / checkpoint_file) == item["modelSha256"]
    codec_expected = next((entry["sha256"] for entry in item.get("artifactFiles", []) if entry["path"] == "dacvae/model.safetensors"), item.get("codecSha256"))
    codec_valid = _sha256(codec_file) == codec_expected
    if not model_valid:
        (model / checkpoint_file).unlink(missing_ok=True)
    if not codec_valid:
        codec_file.unlink(missing_ok=True)
    if not model_valid or not codec_valid:
        raise ValueError("モデルまたはCodecのSHA-256が一致しません。")
    for artifact in item.get("artifactFiles", []):
        artifact_path = model / artifact["path"]
        if not artifact_path.is_file() or _sha256(artifact_path) != artifact["sha256"]:
            artifact_path.unlink(missing_ok=True)
            raise ValueError(f"モデル資産 {artifact['path']} のSHA-256が一致しません。")
    _publish_model_directory(model, model_target)
    if not mlx and not codec_target.exists():
        codec.replace(codec_target)
    registry = deps.read_tts_registry()
    if mlx and not any(entry.get("id") == mlx_engine_id(item) for entry in registry["engines"]):
        registry["engines"].append({
            "id": mlx_engine_id(item), "displayName": f"MLX Audio {mlx_runtime(item)['version']}", "source": "managed",
            "repo": "mlx-audio", "commit": mlx_runtime(item)["version"], "path": None, "pythonPath": str(mlx_python),
            "diskBytes": 0, "verification": "verified", "optimizationProfile": item["runtimeProfile"],
            "installedAt": int(time.time()),
        })
    model_id = item.get("baseModelId", item["id"])
    variant_id = item.get("variantId", "pytorch-fp32")
    card = next((entry for entry in registry["models"] if entry.get("id") == model_id), None)
    variant_card = {"id": variant_id, "precision": item.get("precision", "FP32"), "backend": item.get("backend", "pytorch"),
                    "repo": item["repo"], "revision": item["revision"], "path": str(model_target),
                    "codecPath": str(model_target / "dacvae") if mlx else str(codec_target),
                    "pythonPath": str(mlx_python) if mlx_python else None,
                    **({"runtimeEngineId": mlx_engine_id(item)} if mlx else {}),
                    "diskBytes": sum((model_target / path).stat().st_size for path in item.get("downloadFiles") or [checkpoint_file] if (model_target / path).is_file()),
                    "optimizationProfile": item.get("runtimeProfile", "pytorch-fp32"),
                    "computePrecision": item.get("computePrecision", "fp32"), "checkpointFile": checkpoint_file,
                    "quantization": item.get("quantization")}
    if card:
        card.setdefault("installedVariants", []).append(variant_card)
        card["diskBytes"] = sum(int(entry.get("diskBytes") or 0) for entry in card["installedVariants"])
    else:
        card = {
        "id": model_id, "displayName": item.get("baseDisplayName", item["displayName"]), "source": "managed", "repo": item.get("baseRepo", item["repo"]),
        "revision": item.get("baseRevision", item["revision"]), "path": str(model_target), "codecPath": str(model_target / "dacvae" if mlx else codec_target),
        "codecRevision": item.get("codecRevision"), "diskBytes": _tree_bytes(model_target) + (0 if mlx else _tree_bytes(codec_target)),
        "verification": "verified", "installedAt": int(time.time()),
        "license": item["license"], "modelCardUrl": item["modelCardUrl"],
        **{key: item[key] for key in ("author", "releasedAt", "publisher", "provenance", "notice", "tagline", "description") if key in item},
        **{key: item[key] for key in ("generation", "referenceVoice", "voiceDesign", "combinedReferenceCaption", "legacy", "recommendedOrder", "flowParameterization", "fixedSteps", "supportsRuntimeCfg", "supportsQualityPresets")},
        "installedVariants": [variant_card], "activeVariantId": variant_id,
        }
        registry["models"].append(card)
    if not registry.get("defaultModelId"):
        registry["defaultModelId"] = model_id
        registry["defaultEngineId"] = mlx_engine_id(item) if mlx else registry.get("defaultEngineId")
    deps.write_tts_registry(registry)
    shutil.rmtree(staging, ignore_errors=True)


def _finish_install_failure(state: dict[str, Any], error: Exception, installed_engine_id: str | None) -> None:
    if installed_engine_id:
        try:
            deps.delete_tts_asset("engine", installed_engine_id)
        except (OSError, ValueError, HTTPException) as cleanup_error:
            original = "導入をキャンセルしました。" if isinstance(error, InterruptedError) else str(error)
            detail = str(getattr(cleanup_error, "detail", cleanup_error))
            error = OSError(f"{original}\nエンジンの後片付けに失敗しました: {detail}")
    with TTS_JOB_LOCK:
        if isinstance(error, InterruptedError):
            state.update(state="cancelled", stage="cancelled", currentFile=None)
        else:
            category = "disk_full" if "空き容量" in str(error) else "integrity" if "SHA-256" in str(error) else "installation"
            state.update(state="failed", stage="failed", currentFile=None, error=str(error), errorCategory=category)


def _run_install(kind: str, item: dict[str, Any], state: dict[str, Any], cancel: threading.Event) -> None:
    installed_engine_id: str | None = None
    try:
        state["state"] = "running"
        if kind == "model":
            registry = deps.read_tts_registry()
            engine_id = item.get("supportedEngineIds", [None])[0] if item.get("supportedEngineIds") else None
            if engine_id and not any(card.get("id") == engine_id for card in registry["engines"]):
                state.update(stage="engine", currentFile="Irodori-TTS engine / Python environment")
                engine = _catalog_item("engine", engine_id)
                _install_engine(engine, state, cancel)
                installed_engine_id = engine_id
            state.update(stage="model", currentFile=item["displayName"])
            _install_model(item, state, cancel)
        else:
            _install_engine(item, state, cancel)
        with TTS_JOB_LOCK:
            state.update(state="complete", stage="complete", currentFile=None)
    except (OSError, ValueError, subprocess.SubprocessError, HTTPException) as error:
        _finish_install_failure(state, error, installed_engine_id)
    except Exception as error:  # noqa: BLE001 - an unexpected bug must still end the job, or every later install gets 409
        traceback.print_exc()
        _finish_install_failure(state, error, installed_engine_id)


def start_tts_install(kind: str, asset_id: str) -> dict[str, Any]:
    if kind not in {"engine", "model"}:
        raise HTTPException(status_code=422, detail="資産種別が不正です。")
    item = _catalog_item(kind, asset_id)
    registry = deps.read_tts_registry()
    if any(card.get("id") == asset_id for card in registry["engines" if kind == "engine" else "models"]):
        raise HTTPException(status_code=409, detail="この資産は導入済みです。")
    state, cancel = _job(kind, asset_id)
    threading.Thread(target=_run_install, args=(kind, item, state, cancel), daemon=True).start()
    return dict(state)


def start_tts_variant_install(model_id: str, variant_id: str) -> dict[str, Any]:
    item = _catalog_variant(model_id, variant_id)
    registry = deps.read_tts_registry()
    card = next((entry for entry in registry["models"] if entry.get("id") == model_id), None)
    if card and any(entry.get("id") == variant_id for entry in card.get("installedVariants", [])):
        raise HTTPException(status_code=409, detail="このバリアントは導入済みです。")
    state, cancel = _job("model", item["id"])
    threading.Thread(target=_run_install, args=("model", item, state, cancel), daemon=True).start()
    return dict(state)


def tts_install_status(job_id: str) -> dict[str, Any]:
    with TTS_JOB_LOCK:
        if job_id not in TTS_JOBS:
            raise HTTPException(status_code=404, detail="TTS導入ジョブが見つかりません。")
        return dict(TTS_JOBS[job_id])


def cancel_tts_install(job_id: str) -> dict[str, Any]:
    with TTS_JOB_LOCK:
        if job_id not in TTS_CANCEL:
            raise HTTPException(status_code=404, detail="TTS導入ジョブが見つかりません。")
        if TTS_JOBS[job_id]["state"] in {"complete", "failed", "cancelled"}:
            return dict(TTS_JOBS[job_id])
        TTS_CANCEL[job_id].set()
        TTS_JOBS[job_id]["state"] = "cancelling"
        return dict(TTS_JOBS[job_id])


deps.register(__name__, ["cancel_tts_install", "start_tts_install", "start_tts_variant_install", "tts_install_status"])

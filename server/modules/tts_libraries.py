from __future__ import annotations

from server.platform_support import environment_python

import hashlib
import os
import re
from server import subprocess_boundary as subprocess
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from server.app_deps import time
from server.modules.tts_catalog import MODEL_SPECS
from server.registry import deps

SCAN_MAX_DEPTH = 7
SCAN_MAX_DIRECTORIES = 2500
LIBRARY_MODEL_JOBS: dict[str, dict[str, Any]] = {}
LIBRARY_MODEL_CANCEL: dict[str, threading.Event] = {}
LIBRARY_MODEL_LOCK = threading.Lock()
IGNORED_SCAN_DIRECTORIES = {".git", ".venv", "__pycache__", "node_modules", "blobs", ".locks"}


def _engine_commit(engine: Path) -> str | None:
    try:
        value = subprocess.check_output(
            ["git", "-C", str(engine), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=3,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return value if re.fullmatch(r"[0-9a-f]{40}", value) else None


def _path_id(prefix: str, path: Path) -> str:
    digest = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _inside(root: Path, value: str, label: str) -> Path:
    return _inside_roots([root], value, label)


def _inside_roots(roots: list[Path], value: str, label: str) -> Path:
    path = Path(value).expanduser()
    try:
        resolved = path.resolve(strict=True)
        if not any(resolved.is_relative_to(root.resolve(strict=True)) for root in roots):
            raise ValueError
    except (OSError, ValueError):
        raise HTTPException(status_code=422, detail=f"{label}は接続先またはIrodori-TTS共有キャッシュ内にある必要があります。") from None
    return resolved


def _huggingface_asset_roots() -> list[Path]:
    hub_override = os.getenv("HF_HUB_CACHE")
    home = Path(os.getenv("HF_HOME", "~/.cache/huggingface")).expanduser()
    hub = Path(hub_override).expanduser() if hub_override else (home if home.name == "hub" else home / "hub")
    if not hub.is_dir():
        return []
    roots = [path for path in hub.glob("models--Aratako--Irodori-TTS-*") if path.is_dir()]
    anime = hub / "models--phasefield-audio--Irodori-TTS-v4.1-Anime"
    if anime.is_dir():
        roots.append(anime)
    codec = hub / "models--Aratako--Semantic-DACVAE-Japanese-32dim"
    if codec.is_dir():
        roots.append(codec)
    legacy_tokenizer = hub / "models--llm-jp--llm-jp-3-150m"
    if legacy_tokenizer.is_dir():
        roots.append(legacy_tokenizer)
    return roots


def _tokenizer_dir(model: Path) -> Path | None:
    candidates = (model / "tokenizer", model / "tokenizer.json")
    return next((path for path in candidates if path.is_dir() or path.is_file()), None)


def _shared_tokenizer(model: Path, asset_roots: list[Path]) -> Path | None:
    model_name = str(model).lower()
    if "irodori-tts-500m-v3" not in model_name:
        return None
    for root in asset_roots:
        if root.name != "models--llm-jp--llm-jp-3-150m":
            continue
        snapshots = root / "snapshots"
        if snapshots.is_dir():
            for snapshot in sorted(snapshots.iterdir()):
                if snapshot.is_dir() and (snapshot / "tokenizer.json").is_file():
                    return snapshot
    return None


def _model_candidate_identity(path: Path, library_root: Path) -> dict[str, str | None]:
    cache_root = next((parent for parent in path.parents if parent.name.startswith("models--")), None)
    repo = None
    if cache_root:
        parts = cache_root.name.split("--", 2)
        repo = "/".join(parts[1:]) if len(parts) == 3 else None
    spec = next((item for item in MODEL_SPECS if item[0] == repo), None)
    revision = path.name if path.parent.name == "snapshots" else None
    if spec:
        return {"displayName": spec[1], "repo": repo, "revision": revision, "location": repo}
    try:
        location = str(path.relative_to(library_root))
    except ValueError:
        location = repo or str(path)
    return {"displayName": cache_root.name.removeprefix("models--").replace("--", "/") if cache_root else path.name,
            "repo": repo, "revision": revision, "location": location}


def _is_unsupported_v2_candidate(model: dict[str, Any]) -> bool:
    identity = f"{model.get('repo') or ''} {model.get('path') or ''}".lower()
    return "irodori-tts-500m-v2" in identity


def _discover_library(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], bool]:
    engines: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    codecs: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    visited = 0
    limited = False

    def onerror(error: OSError) -> None:
        warnings.append({"code": "unreadable", "path": error.filename or str(root), "message": "フォルダを読み取れませんでした。"})

    for directory, names, files in os.walk(root, topdown=True, followlinks=False, onerror=onerror):
        current = Path(directory)
        depth = len(current.relative_to(root).parts)
        names[:] = [name for name in names if name not in IGNORED_SCAN_DIRECTORIES and not (current / name).is_symlink()]
        if depth >= SCAN_MAX_DEPTH:
            if names:
                limited = True
            names[:] = []
        visited += 1
        if visited >= SCAN_MAX_DIRECTORIES:
            limited = True
            break
        file_set = set(files)
        if "infer.py" in file_set and (current / "irodori_tts").is_dir():
            python = environment_python(current / ".venv")
            engines.append({"id": _path_id("engine", current), "path": str(current), "pythonPath": str(python) if python.is_file() and os.access(python, os.X_OK) else None})
        if "model.safetensors" in file_set:
            tokenizer = _tokenizer_dir(current)
            models.append({"id": _path_id("candidate", current), "path": str(current), "tokenizerPath": str(tokenizer) if tokenizer else None})
        if "weights.pth" in file_set:
            codecs.append({"id": _path_id("codec", current), "path": str(current)})
    return engines, models, codecs, warnings, limited


def _scan_warnings(root: Path, engines: list[dict[str, Any]], models: list[dict[str, Any]], codecs: list[dict[str, Any]], warnings: list[dict[str, str]], limited: bool) -> None:
    if limited:
        warnings.append({"code": "scan-limit", "path": str(root), "message": "走査上限に達したため、一部のフォルダは確認していません。"})
    if not engines:
        warnings.append({"code": "engine-missing", "path": str(root), "message": "Irodori-TTSエンジンが見つかりません。"})
    for engine in engines:
        if not engine["pythonPath"]:
            warnings.append({"code": "python-missing", "path": engine["path"], "message": "実行可能な.venv/bin/pythonがありません。"})
    if not codecs:
        warnings.append({"code": "codec-missing", "path": str(root), "message": "Codecのweights.pthが見つかりません。"})
    for model in models:
        if not model["tokenizerPath"]:
            warnings.append({"code": "tokenizer-missing", "path": model["path"], "message": "tokenizerが見つかりません。"})


def scan_tts_library(path_value: str) -> dict[str, Any]:
    root = Path(path_value).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise HTTPException(status_code=422, detail="読取可能な接続先フォルダの絶対パスを指定してください。")
    root = root.resolve()
    engines, models, codecs, warnings, limited = _discover_library(root)
    asset_roots = _huggingface_asset_roots() if engines else []
    for asset_root in asset_roots:
        _, cached_models, cached_codecs, cached_warnings, cached_limited = _discover_library(asset_root)
        models.extend(cached_models)
        codecs.extend(cached_codecs)
        warnings.extend(cached_warnings)
        limited = limited or cached_limited
    for model in models:
        tokenizer = _shared_tokenizer(Path(model["path"]), asset_roots)
        if not model["tokenizerPath"] and tokenizer:
            model["tokenizerPath"] = str(tokenizer)
        model.update(_model_candidate_identity(Path(model["path"]), root))
    models = [model for model in models if not _is_unsupported_v2_candidate(model)]
    _scan_warnings(root, engines, models, codecs, warnings, limited)
    return {"root": str(root), "displayName": root.name, "engines": engines, "models": models, "codecs": codecs, "warnings": warnings, "limited": limited,
            "assetRoots": [str(path.resolve()) for path in asset_roots]}


def register_tts_library(root_value: str, engine_value: str, display_name: str | None = None) -> dict[str, Any]:
    root = Path(root_value).expanduser().resolve(strict=True)
    engine = _inside(root, engine_value, "エンジン")
    python = environment_python(engine / ".venv")
    if not (engine / "infer.py").is_file() or not (engine / "irodori_tts").is_dir():
        raise HTTPException(status_code=422, detail="選択したフォルダはIrodori-TTSエンジンではありません。")
    if not python.is_file() or not os.access(python, os.X_OK):
        raise HTTPException(status_code=422, detail="エンジン内に実行可能な.venv/bin/pythonがありません。")
    registry = deps.read_tts_registry()
    library_id = _path_id("library", root)
    card = next((item for item in registry["libraries"] if item.get("id") == library_id), None)
    value = {"id": library_id, "displayName": (display_name or root.name).strip() or root.name,
             "root": str(root), "engineId": _path_id("engine", engine), "enginePath": str(engine),
             "pythonPath": str(python), "engineCommit": _engine_commit(engine),
             "assetRoots": [str(path.resolve()) for path in _huggingface_asset_roots()],
             "available": True, "checkedAt": int(time.time())}
    if card is None:
        registry["libraries"].append(value)
    else:
        card.update(value)
    deps.write_tts_registry(registry)
    return deps.tts_registry_view()


def disconnect_tts_library(library_id: str) -> dict[str, Any]:
    registry = deps.read_tts_registry()
    if any(model.get("libraryId") == library_id for model in registry["models"]):
        raise HTTPException(status_code=409, detail="先にこの接続先のモデルをすべて登録解除してください。")
    if not any(item.get("id") == library_id for item in registry["libraries"]):
        raise HTTPException(status_code=404, detail="接続先が見つかりません。")
    registry["libraries"] = [item for item in registry["libraries"] if item.get("id") != library_id]
    deps.write_tts_registry(registry)
    return deps.tts_registry_view()


def _sha256(path: Path, job: dict[str, Any], cancel: threading.Event) -> str:
    digest = hashlib.sha256()
    total = path.stat().st_size
    job.update(totalBytes=total, processedBytes=0, currentFile=path.name)
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            if cancel.is_set():
                raise InterruptedError
            digest.update(chunk)
            job["processedBytes"] += len(chunk)
    return digest.hexdigest()


def _verify_library_model(job_id: str, library_id: str, model_value: str, codec_value: str) -> None:
    job, cancel = LIBRARY_MODEL_JOBS[job_id], LIBRARY_MODEL_CANCEL[job_id]
    try:
        job.update(state="running", stage="モデルを検証中")
        registry = deps.read_tts_registry()
        library = next((item for item in registry["libraries"] if item.get("id") == library_id), None)
        if not library:
            raise ValueError("接続先が見つかりません。")
        roots = [Path(library["root"]), *(Path(value) for value in library.get("assetRoots", []))]
        model = _inside_roots(roots, model_value, "モデル")
        codec = _inside_roots(roots, codec_value, "Codec")
        tokenizer = _tokenizer_dir(model) or _shared_tokenizer(model, roots)
        if tokenizer is None or not (codec / "weights.pth").is_file():
            raise ValueError("tokenizerまたはCodecが不足しています。")
        model_hash = _sha256(model / "model.safetensors", job, cancel)
        spec = next((item for item in deps.tts_catalog()["models"] if item["modelSha256"] == model_hash), None)
        if spec is None:
            raise ValueError("標準モデルの検証済みハッシュと一致しません。")
        job["stage"] = "Codecを検証中"
        if _sha256(codec / "weights.pth", job, cancel) != spec["codecSha256"]:
            raise ValueError("Codecのハッシュが一致しません。")
        registry = deps.read_tts_registry()
        duplicate = next((item for item in registry["models"] if item.get("repo") == spec["repo"] and item.get("revision") == spec["revision"]), None)
        if duplicate:
            duplicate.update({"source": "external", "libraryId": library_id, "engineId": library["engineId"],
                              "path": str(model), "codecPath": str(codec), "tokenizerPath": str(tokenizer)})
            duplicate.pop("diskUsageFingerprint", None)
            deps.refresh_external_model_disk_usage(duplicate)
            deps.write_tts_registry(registry)
            job.update(state="complete", stage="接続先を更新", modelId=duplicate["id"], duplicate=True)
            return
        model_id = spec["id"]
        registry["models"].append({key: spec.get(key) for key in ("id", "displayName", "repo", "revision", "license", "modelCardUrl", "author", "releasedAt", "publisher", "provenance", "notice", "tagline", "description", "generation", "referenceVoice", "voiceDesign", "combinedReferenceCaption", "legacy", "recommendedOrder", "flowParameterization", "fixedSteps", "supportsRuntimeCfg", "supportsQualityPresets")} | {
            "source": "external", "libraryId": library_id, "engineId": library["engineId"], "path": str(model),
            "codecPath": str(codec), "tokenizerPath": str(tokenizer), "codecRevision": spec["codecRevision"],
            "diskBytes": None, "verification": "verified", "installedAt": int(time.time()),
        })
        deps.refresh_external_model_disk_usage(registry["models"][-1])
        deps.write_tts_registry(registry)
        job.update(state="complete", stage="登録完了", modelId=model_id, duplicate=False)
    except InterruptedError:
        job.update(state="cancelled", stage="取消済み")
    except (OSError, ValueError, HTTPException) as error:
        detail = error.detail if isinstance(error, HTTPException) else str(error)
        job.update(state="failed", stage="検証失敗", error=detail)


def start_library_model_registration(library_id: str, model_path: str, codec_path: str) -> dict[str, Any]:
    job_id = uuid4().hex
    job = {"id": job_id, "libraryId": library_id, "state": "queued", "stage": "検証待ち", "processedBytes": 0,
           "totalBytes": 0, "currentFile": None, "error": None, "modelId": None, "duplicate": False}
    with LIBRARY_MODEL_LOCK:
        LIBRARY_MODEL_JOBS[job_id] = job
        LIBRARY_MODEL_CANCEL[job_id] = threading.Event()
    threading.Thread(target=_verify_library_model, args=(job_id, library_id, model_path, codec_path), daemon=True).start()
    return dict(job)


def library_model_job(job_id: str) -> dict[str, Any]:
    job = LIBRARY_MODEL_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="登録ジョブが見つかりません。")
    return dict(job)


def cancel_library_model_job(job_id: str) -> dict[str, Any]:
    job = LIBRARY_MODEL_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="登録ジョブが見つかりません。")
    if job["state"] in {"queued", "running"}:
        LIBRARY_MODEL_CANCEL[job_id].set()
        job.update(state="cancelling", stage="取消中")
    return dict(job)


deps.register(__name__, ["cancel_library_model_job", "disconnect_tts_library", "library_model_job", "register_tts_library",
                         "scan_tts_library", "start_library_model_registration"])

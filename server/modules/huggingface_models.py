from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, hf_hub_url
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from server.app_deps import HTTPException, keyring
from server.modules.constants import MTP_TARGET_REPO, MTP_TARGET_REVISION
from server.modules.huggingface_metadata import cached_size, fetch_metadata_sizes, inferred_tags
from server.registry import deps
from server.modules.llm_runtime_binding import serialized
from server.modules.huggingface_search_order import hub_search_order, order_search_results
from server.modules.huggingface_gguf_catalog import enrich_search_model
from server.modules.huggingface_preparation import register_download, download_status, cancel_preparation, pinned_revision, pin_files, addition_active

HF_ACCOUNT = "huggingface-token"
HF_DOWNLOADS: dict[str, dict[str, Any]] = {}
HF_CANCEL: dict[str, threading.Event] = {}
HF_LOCK = threading.RLock()
HF_SEARCH_CACHE: dict[tuple[str, tuple[str, ...], str], tuple[float, dict[str, Any]]] = {}
HF_SEARCH_CACHE_SECONDS = 10 * 60
HF_SEARCH_CACHE_LIMIT = 128
PINNED_REVISIONS = {
    "mlx-community/gemma-4-31b-it-nvfp4": "a0a935b105621b98907915fa12f05348bb9c3c24",
}
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_PARALLELISM = 8
MIN_PARALLEL_FILE_BYTES = 64 * 1024 * 1024
PARTIAL_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
PARTIAL_CHECKPOINT_BYTES = 16 * 1024 * 1024


class _RangeUnsupportedError(Exception):
    pass


def _token() -> str | None:
    try:
        return keyring.get_password(deps.KEYCHAIN_SERVICE, HF_ACCOUNT) or None
    except Exception:
        # Public repositories remain searchable when Keychain is locked or
        # temporarily unavailable. Gated access will still fail as auth.
        return None


def set_huggingface_token(token: str) -> dict[str, bool]:
    try:
        if token.strip():
            keyring.set_password(deps.KEYCHAIN_SERVICE, HF_ACCOUNT, token.strip())
        else:
            try:
                keyring.delete_password(deps.KEYCHAIN_SERVICE, HF_ACCOUNT)
            except keyring.errors.PasswordDeleteError:
                pass
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Hugging Face tokenをKeychainへ保存できません: {error}") from error
    return {"hasToken": bool(token.strip())}


def huggingface_token_status() -> dict[str, bool]:
    return {"hasToken": bool(_token())}


def _compatibility(model: Any) -> tuple[str, str | None]:
    tags = {str(tag).lower() for tag in (getattr(model, "tags", None) or [])}
    library = str(getattr(model, "library_name", "") or "").lower()
    if "gguf" in tags or library in {"transformers", "gguf"} and "mlx" not in tags:
        return "incompatible", "MLX形式ではありません。"
    if "mlx" in tags or library.startswith("mlx") or str(model.id).lower().startswith("mlx-community/"):
        return "mlx", None
    return "unknown", "MLX互換性を判定できません。ダウンロード後に基本動作確認してください。"


def _model_result(model: Any) -> dict[str, Any]:
    compatibility, warning = _compatibility(model)
    revision = str(getattr(model, "sha", "") or "")
    repo_id = str(model.id)
    tags = inferred_tags(str(model.id).split("/")[-1])
    mlx_tag = {"kind": "compatibility", "value": "MLX"}
    if compatibility == "mlx" and mlx_tag not in tags:
        tags.append(mlx_tag)
    if repo_id == MTP_TARGET_REPO and revision == MTP_TARGET_REVISION:
        tags.append({"kind": "compatibility", "value": "MTP対応"})
    return {"repoId": repo_id, "publisher": repo_id.split("/", 1)[0] if "/" in repo_id else "",
            "displayName": repo_id.split("/")[-1],
            "downloads": int(getattr(model, "downloads", 0) or 0), "updatedAt": str(getattr(model, "last_modified", "") or ""),
            "gated": bool(getattr(model, "gated", False)), "compatibility": compatibility, "warning": warning,
            "revision": revision, "downloadSizeBytes": cached_size(str(model.id), revision),
            "inferredTags": tags}


_PARAMETER_TOKEN = re.compile(r"(?i)^(\d+(?:\.\d+)?)[bt]$")
_QUANTIZATION_TOKENS = {
    "mxfp4": "MXFP4", "nvfp4": "NVFP4", "fp4": "FP4", "bf16": "BF16", "fp16": "FP16",
    "int4": "INT4", "int8": "INT8", "q4": "Q4", "q8": "Q8", "4bit": "4bit", "8bit": "8bit",
}


_inferred_tags = inferred_tags


def huggingface_metadata_sizes(items: list[dict[str, str]]) -> dict[str, Any]:
    try:
        return fetch_metadata_sizes(items, _token)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _model_info_with_optional_token(api: HfApi, repo_id: str, **options: Any) -> tuple[Any, str | None]:
    try:
        return api.model_info(repo_id, token=False, **options), None
    except (GatedRepoError, RepositoryNotFoundError):
        token = _token()
        if not token:
            raise
        return api.model_info(repo_id, token=token, **options), token


def _matches_search_filters(model: dict[str, Any], filters: tuple[str, ...]) -> bool:
    keys = {f"{tag['kind']}:{tag['value']}" for tag in model["inferredTags"]}
    keys.add(f"publisher:{model['publisher']}")
    return all(value in keys for value in filters if not (WINDOWS_MODEL_CATALOG and value.startswith("quantization:") and "ggufVariants" not in model))


def _search_text(query: str, filters: tuple[str, ...]) -> str:
    searchable = [value.split(":", 1)[1] for value in filters
                  if value.split(":", 1)[0] not in ({"compatibility", "quantization"} if WINDOWS_MODEL_CATALOG else {"compatibility"})]
    return " ".join(dict.fromkeys([query.strip(), *searchable])).strip()


def search_huggingface_models(query: str, selected_filters: list[str] | None = None, order: str = "downloads") -> dict[str, Any]:
    hub_order = hub_search_order(order)
    allowed = {"publisher", "family", "parameters", "quantization", "purpose", "role", "compatibility"}
    filters = tuple(sorted(set(selected_filters or [])))
    if any(":" not in value or value.split(":", 1)[0] not in allowed or not value.split(":", 1)[1]
           for value in filters):
        raise HTTPException(status_code=422, detail="検索タグが不正です。")
    windows = WINDOWS_MODEL_CATALOG
    cache_key = (("gguf:" if windows else "mlx:") + query.strip().casefold(), filters, order)
    now = time.monotonic()
    with HF_LOCK:
        cached = HF_SEARCH_CACHE.get(cache_key)
        if cached and now - cached[0] < HF_SEARCH_CACHE_SECONDS:
            return cached[1]
    api = HfApi(token=False)
    value = query.strip()
    try:
        if "/" in value and " " not in value:
            models = [_model_info_with_optional_token(api, value, files_metadata=False)[0]]
        else:
            models = list(api.list_models(search=_search_text(value, filters) or None, filter="gguf" if windows else "mlx",
                                          sort=hub_order, limit=30, full=True))
    except RepositoryNotFoundError as error:
        raise HTTPException(status_code=404, detail="Hugging Face repositoryが見つかりません。") from error
    except HfHubHTTPError as error:
        raise HTTPException(status_code=502, detail=f"Hugging Face検索に失敗しました: {error}") from error
    results = [_model_result(model) for model in models]
    if windows:
        for item, model in zip(results, models, strict=True):
            enrich_search_model(item, model)
    expected = "gguf" if windows else "mlx"
    results = [item for item in results if item["compatibility"] == expected and
               _matches_search_filters(item, filters)]
    response = {"models": order_search_results(results, order), "mlxOnly": not windows, "format": "GGUF" if windows else "MLX"}
    with HF_LOCK:
        HF_SEARCH_CACHE[cache_key] = (now, response)
        if len(HF_SEARCH_CACHE) > HF_SEARCH_CACHE_LIMIT:
            oldest = min(HF_SEARCH_CACHE, key=lambda key: HF_SEARCH_CACHE[key][0])
            del HF_SEARCH_CACHE[oldest]
    return response


def _managed_target(repo_id: str) -> Path:
    safe = "--".join(part for part in repo_id.split("/") if part not in {"", ".", ".."})
    if not safe or len(safe) > 180:
        safe = hashlib.sha256(repo_id.encode()).hexdigest()
    return deps.LOCAL_LLM_ROOT / "models" / safe


def cleanup_stale_huggingface_partials(now: float | None = None) -> int:
    root = deps.LOCAL_LLM_ROOT / "models"
    if not root.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - PARTIAL_CACHE_MAX_AGE_SECONDS
    removed = 0
    for path in root.rglob("*"):
        if path.is_file() and (path.name.endswith(".part") or path.name.endswith(".part.json")):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                pass
    return removed


@deps.app.on_event("startup")
def cleanup_huggingface_download_cache() -> None:
    cleanup_stale_huggingface_partials()


def _write_partial_manifest(path: Path, size: int, revision: str, completed: list[int]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"size": size, "revision": revision, "completed": completed}))
    temporary.replace(path)


def _partial_progress(partial: Path) -> int:
    manifest = partial.with_suffix(partial.suffix + ".json")
    if manifest.is_file():
        try:
            return sum(max(0, int(value)) for value in json.loads(manifest.read_text()).get("completed", []))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0
    return partial.stat().st_size if partial.is_file() else 0


def _require_range_support(url: str, token: str | None) -> None:
    headers = {"Range": "bytes=0-0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        if getattr(response, "status", 200) != 206:
            raise _RangeUnsupportedError


def _load_parallel_progress(partial: Path, manifest: Path, file_size: int,
                            revision: str, segments: list[tuple[int, int]]) -> list[int]:
    completed = [0] * len(segments)
    if manifest.is_file():
        try:
            saved = json.loads(manifest.read_text())
            valid = saved.get("size") == file_size and saved.get("revision") == revision
            if valid and len(saved.get("completed", [])) == len(segments):
                return [min(int(value), segments[index][1]) for index, value in enumerate(saved["completed"])]
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return completed
    if partial.is_file() and partial.stat().st_size < file_size:
        legacy_size = partial.stat().st_size
        return [max(0, min(size, legacy_size - offset)) for offset, size in segments]
    return completed


def _parallel_download_file(repo_id: str, filename: str, revision: str, target: Path,
                            state: dict[str, Any], cancel: threading.Event, token: str | None,
                            file_size: int) -> None:
    destination = target / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.part")
    manifest = partial.with_suffix(partial.suffix + ".json")
    url = hf_hub_url(repo_id, filename, revision=revision)
    _require_range_support(url, token)
    segment_size = max(MIN_PARALLEL_FILE_BYTES, (file_size + DOWNLOAD_PARALLELISM - 1) // DOWNLOAD_PARALLELISM)
    segments = [(offset, min(segment_size, file_size - offset)) for offset in range(0, file_size, segment_size)]
    completed = _load_parallel_progress(partial, manifest, file_size, revision, segments)
    partial.touch(exist_ok=True)
    with partial.open("r+b") as output:
        output.truncate(file_size)
    lock = threading.Lock()
    _write_partial_manifest(manifest, file_size, revision, completed)
    stop = threading.Event()

    def download_segment(index: int, offset: int, size: int) -> None:
        position = completed[index]
        if position >= size:
            return
        headers = {"Range": f"bytes={offset + position}-{offset + size - 1}"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("r+b", buffering=0) as output:
            if getattr(response, "status", 200) != 206:
                stop.set()
                raise _RangeUnsupportedError
            checkpoint = position
            while position < size:
                if cancel.is_set() or stop.is_set():
                    raise InterruptedError
                chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, size - position))
                if not chunk:
                    raise OSError("Hugging Faceからファイル全体を取得できませんでした。")
                if sys.platform == "win32":
                    # Each range worker owns its file handle, so its seek position is
                    # independent. Windows does not provide os.pwrite.
                    output.seek(offset + position)
                    output.write(chunk)
                else:
                    os.pwrite(output.fileno(), chunk, offset + position)
                position += len(chunk)
                with lock:
                    completed[index] = position
                    state["downloadedBytes"] += len(chunk)
                    state["currentFile"] = f"{filename} ({sum(value == part[1] for value, part in zip(completed, segments, strict=True))}/{len(segments)})"
                    if position - checkpoint >= PARTIAL_CHECKPOINT_BYTES or position == size:
                        os.fsync(output.fileno())
                        _write_partial_manifest(manifest, file_size, revision, completed)
                        checkpoint = position

    try:
        with ThreadPoolExecutor(max_workers=min(DOWNLOAD_PARALLELISM, len(segments)), thread_name_prefix="hf-range") as executor:
            futures = [executor.submit(download_segment, index, offset, size) for index, (offset, size) in enumerate(segments)]
            for future in as_completed(futures):
                future.result()
    except BaseException:
        stop.set()
        raise
    if cancel.is_set():
        raise InterruptedError
    partial.replace(destination)
    manifest.unlink(missing_ok=True)


def _download_file(repo_id: str, filename: str, revision: str, target: Path,
                   state: dict[str, Any], cancel: threading.Event, token: str | None = None,
                   file_size: int | None = None) -> None:
    destination = target / filename
    try:
        destination.resolve().relative_to(target.resolve())
    except ValueError as error:
        raise ValueError("repository内に不正なファイルパスがあります。") from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    if file_size and file_size >= MIN_PARALLEL_FILE_BYTES:
        try:
            _parallel_download_file(repo_id, filename, revision, target, state, cancel, token, file_size)
            return
        except _RangeUnsupportedError:
            partial = destination.with_name(f"{destination.name}.part")
            state["downloadedBytes"] = max(0, state["downloadedBytes"] - _partial_progress(partial))
            partial.unlink(missing_ok=True)
            partial.with_suffix(partial.suffix + ".json").unlink(missing_ok=True)
    partial = destination.with_name(f"{destination.name}.part")
    offset = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(hf_hub_url(repo_id, filename, revision=revision), headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        if offset and getattr(response, "status", 200) != 206:
            state["downloadedBytes"] = max(0, state["downloadedBytes"] - offset)
            offset = 0
        mode = "ab" if offset else "wb"
        with partial.open(mode) as output:
            while True:
                if cancel.is_set():
                    raise InterruptedError
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                if cancel.is_set():
                    raise InterruptedError
                output.write(chunk)
                state["downloadedBytes"] += len(chunk)
    if cancel.is_set():
        raise InterruptedError
    partial.replace(destination)


def _download_repo(repo_id: str, state: dict[str, Any], cancel: threading.Event, variant: str | None = None) -> None:
    target = _managed_target(repo_id)
    try:
        api = HfApi(token=False)
        info, token = _model_info_with_optional_token(
            api, repo_id, revision=pinned_revision(state, PINNED_REVISIONS.get(repo_id)), files_metadata=True,
        )
        windows = WINDOWS_MODEL_CATALOG
        compatibility, _warning = deps.gguf_compatibility(info) if windows else _compatibility(info)
        if compatibility != ("gguf" if windows else "mlx"):
            raise ValueError("GGUF形式と確認できないrepositoryです。" if windows else "MLX形式と確認できないrepositoryです。")
        if windows:
            candidates = deps.variants_from_info(repo_id, info)["variants"]
            selected = next((item for item in candidates if item["id"] == variant), None)
            if not selected:
                raise ValueError("取得するGGUF量子化variantを選択してください。")
            selected_files = set(selected["files"])
            files = [item for item in info.siblings or [] if item.rfilename in selected_files]
        else:
            files = [item for item in (info.siblings or []) if item.rfilename and not item.rfilename.startswith((".git/", "onnx/"))]
        pin_files(state, target, files, info.sha)
        total = sum(int(item.size or 0) for item in files)
        state["totalBytes"] = total
        target.mkdir(parents=True, exist_ok=True)
        if total and shutil.disk_usage(target).free < total + 2 * 1024**3:
            raise OSError("空き容量が不足しています。")
        state["state"] = "downloading"
        state["downloadedBytes"] = sum(
            (target / item.rfilename).stat().st_size if (target / item.rfilename).is_file()
            else _partial_progress((target / item.rfilename).with_name(f"{Path(item.rfilename).name}.part"))
            for item in files
        )
        for item in files:
            if cancel.is_set():
                raise InterruptedError
            state["currentFile"] = item.rfilename
            revision = PINNED_REVISIONS.get(repo_id, info.sha)
            _download_file(repo_id, item.rfilename, revision, target, state, cancel, token, int(item.size or 0))
        revision = PINNED_REVISIONS.get(repo_id, info.sha)
        (target / ".scena-model.json").write_text(json.dumps({"repo": repo_id, "revision": revision}, indent=2) + "\n")
        if not windows:
            deps.rebuild_local_llm_discovery()
        card = deps.register_local_llm_card(target.name, source="managed", metadata={
            "displayName": repo_id.split("/")[-1], "repoId": repo_id, "revision": revision,
            "path": str(target), "format": "GGUF" if windows else "MLX", "diskBytes": state["downloadedBytes"],
            "files": [str(target / item.rfilename) for item in files] if windows else None,
            "engine": "llama.cpp" if windows else "omlx",
        })
        state.update(state="complete", currentFile=None, path=str(target), revision=revision, cardId=card["id"])
    except InterruptedError:
        state.update(state="cancelled", currentFile=None)
    except GatedRepoError:
        state.update(state="failed", errorCategory="authentication", error="Hugging Face側で利用規約へ同意し、tokenを設定してください。")
    except (HfHubHTTPError, OSError, ValueError) as error:
        category = "disk_full" if isinstance(error, OSError) and "容量" in str(error) else "unsupported_format" if isinstance(error, ValueError) else "runtime_crash"
        state.update(state="failed", errorCategory=category, error=str(error), currentFile=None)


@serialized
def start_huggingface_download(repo_id: str, variant: str | None = None) -> dict[str, Any]:
    value = repo_id.strip()
    if "/" not in value or value.startswith(('/', '.')):
        raise HTTPException(status_code=422, detail="organization/model形式のrepo IDを指定してください。")
    existing = next((x for x in HF_DOWNLOADS.values() if x["repoId"] == value
                     and addition_active(x)), None)
    if existing:
        return dict(existing)
    job_id = "hf_" + hashlib.sha256(f"{value}\n{time.time_ns()}".encode()).hexdigest()[:16]
    state = {"id": job_id, "repoId": value, "state": "queued", "downloadedBytes": 0,
             "totalBytes": 0, "currentFile": None, "error": None, "errorCategory": None}
    cancel = threading.Event()
    with HF_LOCK:
        HF_DOWNLOADS[job_id], HF_CANCEL[job_id] = state, cancel
    target = _managed_target(value)
    register_download(target, state, variant)
    threading.Thread(target=_download_repo, args=(value, state, cancel, variant), daemon=True).start()
    return dict(state)


def huggingface_download_status(job_id: str) -> dict[str, Any]:
    with HF_LOCK:
        if job_id not in HF_DOWNLOADS:
            raise HTTPException(status_code=404, detail="Hugging Faceダウンロードが見つかりません。")
        state = dict(HF_DOWNLOADS[job_id])
    return download_status(state)


def cancel_huggingface_download(job_id: str) -> dict[str, Any]:
    with HF_LOCK:
        if job_id not in HF_CANCEL:
            raise HTTPException(status_code=404, detail="Hugging Faceダウンロードが見つかりません。")
        HF_CANCEL[job_id].set()
        if HF_DOWNLOADS[job_id]["state"] in {"queued", "downloading"}:
            HF_DOWNLOADS[job_id]["state"] = "cancelling"
        state = HF_DOWNLOADS[job_id]
    cancel_preparation(state)
    return download_status(state)


deps.register(__name__, ["cancel_huggingface_download", "huggingface_download_status", "huggingface_token_status",
                         "search_huggingface_models", "huggingface_metadata_sizes", "set_huggingface_token", "start_huggingface_download",
                         "cleanup_stale_huggingface_partials"])
WINDOWS_MODEL_CATALOG = sys.platform == "win32"

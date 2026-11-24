from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

from server.app_deps import HTTPException
from server.modules.constants import MTP_TARGET_REPO, MTP_TARGET_REVISION
from server.modules.huggingface_models import _download_file, _partial_progress, _token
from server.registry import deps

MTP_DRAFT_REPO = "google/gemma-4-31B-it-assistant"
MTP_DRAFT_REVISION = "627c5ec1458b9086b841a91e0512fd31fd2fbbf1"
MTP_ASSET_VERSION = 1
JOBS: dict[str, dict[str, Any]] = {}
CANCEL: dict[str, threading.Event] = {}
LOCK = threading.RLock()


def mtp_asset_root() -> Path:
    return deps.LOCAL_LLM_ROOT / ".runtime-assets" / "mtp" / MTP_DRAFT_REVISION


def _manifest_path() -> Path:
    return mtp_asset_root() / ".scena-mtp.json"


def _complete() -> bool:
    try:
        manifest = json.loads(_manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    expected = {"version": MTP_ASSET_VERSION, "repo": MTP_DRAFT_REPO, "revision": MTP_DRAFT_REVISION}
    root = mtp_asset_root()
    return manifest == expected and (root / "config.json").is_file() and any(root.glob("*.safetensors"))


def mtp_asset_status() -> dict[str, Any]:
    active = next((dict(value) for value in JOBS.values() if value["state"] in {"queued", "downloading"}), None)
    root = mtp_asset_root()
    disk_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) if root.exists() else 0
    return {"supportedTargetRepo": MTP_TARGET_REPO, "targetRevision": MTP_TARGET_REVISION,
            "draftRepo": MTP_DRAFT_REPO, "draftRevision": MTP_DRAFT_REVISION,
            "installed": _complete(), "diskBytes": disk_bytes, "download": active,
            "cancelable": active is not None}


def mtp_compatibility(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    supported = metadata.get("repoId") == MTP_TARGET_REPO and metadata.get("revision") == MTP_TARGET_REVISION
    return {"supported": supported, "draftInstalled": _complete() if supported else False}


def resolve_mtp_draft(metadata: dict[str, Any] | None) -> Path:
    compatibility = mtp_compatibility(metadata)
    if not compatibility["supported"]:
        raise HTTPException(status_code=422, detail="このtargetモデルはGemma 4 MTPに対応していません。")
    if not compatibility["draftInstalled"]:
        raise HTTPException(status_code=409, detail="MTP用assistantモデルを先にダウンロードしてください。")
    return mtp_asset_root().resolve()


def _download(state: dict[str, Any], cancel: threading.Event) -> None:
    root = mtp_asset_root()
    try:
        info = HfApi(token=_token()).model_info(MTP_DRAFT_REPO, revision=MTP_DRAFT_REVISION, files_metadata=True)
        files = [item for item in info.siblings or [] if item.rfilename and not item.rfilename.startswith((".git/", "assets/"))]
        total = sum(int(item.size or 0) for item in files)
        root.mkdir(parents=True, exist_ok=True)
        if total and shutil.disk_usage(root).free < total + 2 * 1024**3:
            raise OSError("空き容量が不足しています。")
        token = _token()
        state.update(state="downloading", totalBytes=total)
        state["downloadedBytes"] = sum(
            (root / item.rfilename).stat().st_size if (root / item.rfilename).is_file()
            else _partial_progress((root / item.rfilename).with_name(f"{Path(item.rfilename).name}.part"))
            for item in files
        )
        for item in files:
            if cancel.is_set():
                raise InterruptedError
            state["currentFile"] = item.rfilename
            _download_file(MTP_DRAFT_REPO, item.rfilename, MTP_DRAFT_REVISION, root, state, cancel,
                           token, int(item.size or 0))
        _manifest_path().write_text(json.dumps({"version": MTP_ASSET_VERSION, "repo": MTP_DRAFT_REPO,
                                                "revision": MTP_DRAFT_REVISION}, indent=2) + "\n", encoding="utf-8")
        state.update(state="complete", currentFile=None)
    except InterruptedError:
        state.update(state="cancelled", currentFile=None)
    except GatedRepoError:
        state.update(state="failed", errorCategory="authentication", error="Hugging Faceの認証を確認してください。")
    except (HfHubHTTPError, OSError) as error:
        state.update(state="failed", errorCategory="disk_full" if "容量" in str(error) else "runtime_crash",
                     error=str(error), currentFile=None)


def start_mtp_download() -> dict[str, Any]:
    if _complete():
        return {"id": None, "state": "complete", "downloadedBytes": 0, "totalBytes": 0}
    active = next((dict(value) for value in JOBS.values() if value["state"] in {"queued", "downloading"}), None)
    if active is not None:
        return active
    job_id = "mtp_" + hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:16]
    state = {"id": job_id, "state": "queued", "downloadedBytes": 0, "totalBytes": 0,
             "currentFile": None, "error": None, "errorCategory": None}
    cancel = threading.Event()
    with LOCK:
        JOBS[job_id], CANCEL[job_id] = state, cancel
    threading.Thread(target=_download, args=(state, cancel), daemon=True).start()
    return dict(state)


def cancel_mtp_download(job_id: str) -> dict[str, Any]:
    with LOCK:
        if job_id not in CANCEL:
            raise HTTPException(status_code=404, detail="MTPダウンロードが見つかりません。")
        CANCEL[job_id].set()
        return dict(JOBS[job_id])


def remove_mtp_asset() -> dict[str, Any]:
    if any(value["state"] in {"queued", "downloading"} for value in JOBS.values()):
        raise HTTPException(status_code=409, detail="MTPダウンロードを先に取消してください。")
    if mtp_asset_root().exists():
        shutil.rmtree(mtp_asset_root())
    return mtp_asset_status()


def mtp_download_active() -> bool:
    return any(value["state"] in {"queued", "downloading"} for value in JOBS.values())


deps.register(__name__, ["cancel_mtp_download", "mtp_asset_status", "mtp_compatibility", "mtp_download_active", "remove_mtp_asset",
                         "resolve_mtp_draft", "start_mtp_download"])

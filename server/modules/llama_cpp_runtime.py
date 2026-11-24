from __future__ import annotations

import hashlib
import json
import shutil
import ctypes
import os
import threading
import urllib.request
import uuid
import zipfile
import stat
from pathlib import Path, PurePosixPath
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps

LOCK = threading.RLock()
CANCEL = threading.Event()
JOB: dict[str, Any] = {"state": "idle"}


def _manifest() -> dict[str, Any]:
    path = deps.PROJECT_ROOT / "server" / "catalogs" / "llama-cpp-runtime.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _root() -> Path:
    return deps.LOCAL_LLM_ROOT / "runtimes" / "llama.cpp"


def _runtime_path(version: str, backend: str) -> Path:
    return _root() / f"{version}-{backend}"


def _cuda_driver_available() -> bool:
    if os.name != "nt":
        return False
    try:
        driver = ctypes.WinDLL("nvcuda.dll")
        count = ctypes.c_int()
        return driver.cuInit(0) == 0 and driver.cuDeviceGetCount(ctypes.byref(count)) == 0 and count.value > 0
    except (OSError, AttributeError):
        return False


def nvidia_available() -> bool:
    """Use the desktop's startup topology; manual API starts use CUDA directly."""
    encoded = os.environ.get("SCENA_ACCELERATOR_TOPOLOGY")
    if encoded:
        try:
            topology = json.loads(encoded)
            if isinstance(topology, dict) and topology.get("kind") in {"dedicated", "system-only", "unified"}:
                return topology.get("kind") == "dedicated"
        except (TypeError, ValueError):
            pass
    return _cuda_driver_available()


def recommended_backend() -> str:
    return "cuda" if nvidia_available() else "cpu"


def selected_backend() -> str:
    try:
        value = (_root() / "active-backend").read_text(encoding="utf-8").strip()
        if value in {"cuda", "cpu"}:
            return value
    except OSError:
        pass
    return recommended_backend()


def select_llama_cpp_backend(backend: str | None) -> dict[str, Any]:
    if backend not in {"cuda", "cpu"}:
        raise HTTPException(422, "backendはcudaまたはcpuを指定してください。")
    if backend == "cuda" and not nvidia_available():
        raise HTTPException(409, "NVIDIA GPUを確認できません。CPUを選択してください。")
    _root().mkdir(parents=True, exist_ok=True)
    temporary = _root() / "active-backend.tmp"
    temporary.write_text(backend + "\n", encoding="utf-8")
    temporary.replace(_root() / "active-backend")
    return llama_cpp_runtime_status(backend)


def llama_cpp_runtime_status(backend: str | None = None) -> dict[str, Any]:
    spec = _manifest()
    selected = backend or selected_backend()
    target = _runtime_path(spec["version"], selected)
    ready = (target / ".ready").is_file() and (target / "llama-server.exe").is_file()
    with LOCK:
        job = dict(JOB)
    return {"engine": "llama.cpp", "version": spec["version"], "backend": selected,
            "ready": ready, "path": str(target) if ready else None, "job": job}


def _download(url: str, expected_hash: str, partial: Path) -> Path:
    offset = partial.stat().st_size if partial.is_file() else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        if offset and getattr(response, "status", 200) != 206:
            offset = 0
        length = getattr(response, "headers", {}).get("Content-Length")
        if length:
            with LOCK:
                JOB["totalBytes"] += offset + int(length)
        with partial.open("ab" if offset else "wb") as output:
            while chunk := response.read(1024 * 1024):
                if CANCEL.is_set():
                    raise InterruptedError
                output.write(chunk)
                with LOCK:
                    JOB["downloadedBytes"] += len(chunk)
    digest = hashlib.sha256(partial.read_bytes()).hexdigest()
    if digest != expected_hash:
        partial.unlink(missing_ok=True)
        raise ValueError("llama.cpp配布物のSHA-256が一致しません。")
    completed = partial.with_suffix("")
    partial.replace(completed)
    return completed


def _safe_extract(archive: Path, staging: Path) -> None:
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            path = PurePosixPath(member.filename.replace("\\", "/"))
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("llama.cpp ZIPにsymlinkが含まれています。")
            if path.is_absolute() or ".." in path.parts or member.is_dir():
                if path.is_absolute() or ".." in path.parts:
                    raise ValueError("llama.cpp ZIPに不正なパスがあります。")
                continue
            name = path.name
            keep = name == "llama-server.exe" or name.lower() in {"license", "license.txt", "notice", "notice.txt"} or name.lower().endswith(".dll")
            if not keep:
                continue
            destination = staging / ("LICENSE" if name.lower() in {"license", "license.txt"} else name)
            data = source.read(member)
            if destination.exists() and destination.read_bytes() != data:
                raise ValueError(f"llama.cpp ZIP内で{name}が重複しています。")
            destination.write_bytes(data)


def _install(backend: str) -> None:
    spec = _manifest()
    target = _runtime_path(spec["version"], backend)
    downloads = _root() / "downloads"
    staging = _root() / f".staging-{uuid.uuid4().hex}"
    old = target.with_name(target.name + ".old")
    archives: list[Path] = []
    try:
        downloads.mkdir(parents=True, exist_ok=True)
        staging.mkdir(parents=True)
        with LOCK:
            JOB.update(state="downloading", backend=backend, downloadedBytes=0, totalBytes=0, error=None)
        for index, artifact in enumerate(spec["backends"][backend]["artifacts"]):
            partial = downloads / f"{spec['version']}-{backend}-{index}.zip.partial"
            archives.append(_download(artifact["url"], artifact["sha256"], partial))
        with LOCK:
            JOB["state"] = "verifying"
        for archive in archives:
            _safe_extract(archive, staging)
        if not (staging / "LICENSE").is_file() and spec.get("license", {}).get("sha256"):
            license_spec = spec["license"]
            license_file = _download(license_spec["url"], license_spec["sha256"],
                                     downloads / f"{spec['version']}-LICENSE.partial")
            archives.append(license_file)
            shutil.copyfile(license_file, staging / "LICENSE")
        for required in spec["required"]:
            if not (staging / required).is_file():
                raise ValueError(f"llama.cpp配布物に必須ファイル {required} がありません。")
        (staging / "scena-runtime.json").write_text(json.dumps({"version": spec["version"], "backend": backend,
            "artifacts": spec["backends"][backend]["artifacts"]}, indent=2) + "\n", encoding="utf-8")
        (staging / ".ready").write_text("ready\n", encoding="utf-8")
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.replace(old)
        try:
            staging.replace(target)
        except OSError:
            if old.exists() and not target.exists():
                old.replace(target)
            raise
        active = _root() / "active-backend.tmp"
        active.write_text(backend + "\n", encoding="utf-8")
        active.replace(_root() / "active-backend")
        shutil.rmtree(old, ignore_errors=True)
        for archive in archives:
            archive.unlink(missing_ok=True)
        with LOCK:
            JOB.update(state="complete", path=str(target))
    except InterruptedError:
        with LOCK:
            JOB["state"] = "cancelled"
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        for archive in archives:
            archive.unlink(missing_ok=True)
        with LOCK:
            JOB.update(state="failed", error=str(error))
    finally:
        for archive in archives:
            archive.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def install_llama_cpp_runtime(backend: str | None = None) -> dict[str, Any]:
    selected = backend or recommended_backend()
    if selected not in {"cuda", "cpu"}:
        raise HTTPException(422, "backendはcudaまたはcpuを指定してください。")
    if selected == "cuda" and not nvidia_available():
        raise HTTPException(409, "NVIDIA GPUを確認できません。CPU版を明示的に選択してください。")
    with LOCK:
        if JOB.get("state") in {"downloading", "verifying"}:
            return llama_cpp_runtime_status(selected)
        CANCEL.clear()
        JOB.clear()
        JOB.update(id=uuid.uuid4().hex, state="queued", backend=selected, downloadedBytes=0, totalBytes=0, error=None)
    threading.Thread(target=_install, args=(selected,), daemon=True).start()
    return llama_cpp_runtime_status(selected)


def cancel_llama_cpp_runtime_install() -> dict[str, Any]:
    CANCEL.set()
    with LOCK:
        if JOB.get("state") in {"queued", "downloading", "verifying"}:
            JOB["state"] = "cancelling"
    return llama_cpp_runtime_status(str(JOB.get("backend") or recommended_backend()))


def delete_llama_cpp_runtime(backend: str) -> dict[str, Any]:
    if backend not in {"cuda", "cpu"}:
        raise HTTPException(422, "backendはcudaまたはcpuを指定してください。")
    references = [card for card in deps.read_llm_registry()["cards"]
                  if card.get("source") in {"managed", "external"}]
    if references:
        raise HTTPException(409, "登録モデルが使用しています。先にすべての内蔵LLMモデルを削除してください。")
    with LOCK:
        if JOB.get("state") in {"queued", "downloading", "verifying", "cancelling"}:
            raise HTTPException(409, "llama.cppを準備中です。完了または取消後に削除してください。")
    deps.stop_local_llm()
    spec = _manifest()
    shutil.rmtree(_runtime_path(spec["version"], backend), ignore_errors=False)
    active = _root() / "active-backend"
    if active.is_file() and active.read_text(encoding="utf-8").strip() == backend:
        active.unlink()
    return llama_cpp_runtime_status(backend)


deps.register(__name__, ["cancel_llama_cpp_runtime_install", "delete_llama_cpp_runtime", "install_llama_cpp_runtime",
                         "llama_cpp_runtime_status", "nvidia_available", "recommended_backend", "select_llama_cpp_backend", "selected_backend"])

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import threading
import urllib.request
import uuid
import struct
from server import subprocess_boundary as subprocess
import tempfile
import wave
import zipfile
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps
from server.modules.japanese_lipsync_install import installed_addon_status, verify_packaged_addon
from server.modules.rhubarb_inventory import installed_releases, package_matches, remove_obsolete, replace_runtime
from server.modules.rhubarb_catalog_updates import updated_catalog


CATALOG_PATH = Path(__file__).resolve().parents[1] / "catalogs" / "rhubarb-runtime.json"
INSTALL_LOCK = threading.RLock()
INSTALL_JOB: dict[str, Any] | None = None


def _catalog(*, check_updates=False) -> dict[str, Any]:
    override = os.environ.get("SCENA_RHUBARB_CATALOG")
    if override:
        return json.loads(Path(override).read_text(encoding='utf-8'))
    return updated_catalog(json.loads(CATALOG_PATH.read_text()), deps.RHUBARB_RUNTIMES_ROOT.parent,
                           refresh=check_updates)


def _platform_key() -> str | None:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "darwin" and machine == "arm64":
        return "darwin-arm64"
    if system == "windows" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    return None


def _entry(*, check_updates=False) -> tuple[dict[str, Any], str | None, dict[str, Any] | None]:
    catalog = _catalog(check_updates=check_updates)
    key = _platform_key()
    return catalog, key, catalog.get("platforms", {}).get(key) if key else None


def _runtime_dir(catalog: dict[str, Any], key: str) -> Path:
    return deps.RHUBARB_RUNTIMES_ROOT / str(catalog["releaseId"]) / key


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _installed_runtime(catalog, key, entry):
    target = _runtime_dir(catalog, key)
    candidates = [target, *(release / key for release in installed_releases(deps.RHUBARB_RUNTIMES_ROOT, key))]
    builtin = json.loads(CATALOG_PATH.read_text())
    for root in dict.fromkeys(candidates):
        try:
            marker = json.loads((root / '.ready').read_text(encoding='utf-8'))
            installed_entry = marker.get('entry')
            if installed_entry is None:
                installed_entry = (builtin['platforms'].get(key) if root.parent.name == builtin['releaseId']
                                   else entry if root == target else None)
                legacy_path = CATALOG_PATH.with_name(f'rhubarb-runtime-{root.parent.name}.json')
                if installed_entry is None and legacy_path.is_file():
                    legacy = json.loads(legacy_path.read_text())
                    if legacy['releaseId'] == root.parent.name:
                        installed_entry = legacy['platforms'].get(key)
            if not installed_entry:
                continue
            relative = Path(installed_entry['executable'])
            if relative.is_absolute() or '..' in relative.parts:
                continue
            executable = root / relative
            if (executable.is_file() and _sha256(executable) == installed_entry['executableSha256']
                    and package_matches(root, installed_entry)):
                return executable, root
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None, None


def rhubarb_executable() -> Path:
    catalog, key, entry = _entry()
    if not key or not entry:
        raise RuntimeError("このOSまたはCPUではRhubarbを利用できません。")
    executable, _root = _installed_runtime(catalog, key, entry)
    if executable is None:
        raise RuntimeError("Rhubarbが導入されていないか、再取得が必要です。")
    return executable


def rhubarb_status() -> dict[str, Any]:
    catalog, key, entry = _entry(check_updates=True)
    supported = entry is not None
    available = bool(entry and entry.get("available") and entry.get("archiveSha256") and entry.get("files"))
    executable, installed_root = _installed_runtime(catalog, key, entry) if supported else (None, None)
    ready = executable is not None
    target_ready = bool(ready and installed_root == _runtime_dir(catalog, key)
                        and package_matches(installed_root, entry))
    with INSTALL_LOCK:
        job = dict(INSTALL_JOB) if INSTALL_JOB else None
    addon = installed_addon_status(executable) if ready else None
    releases = installed_releases(deps.RHUBARB_RUNTIMES_ROOT, key)
    installed = ready or bool(releases)
    if not ready and entry and entry.get('japaneseAddon'):
        addon = {"ready": False, "analysisVersion": entry['japaneseAddon']['analysisVersion'],
                 "license": entry['japaneseAddon']['license']}
    return {
        "provider": "Rhubarb",
        "version": catalog["version"],
        "releaseId": catalog["releaseId"],
        "platform": key,
        "supported": supported,
        "available": available,
        "installed": installed,
        "installedReleaseId": releases[0].name if releases else None,
        "updateAvailable": bool(available and installed and not target_ready),
        "ready": ready,
        "archiveBytes": int(entry.get("archiveBytes", 0)) if entry else 0,
        "license": catalog["license"],
        "sourceUrl": catalog["sourceUrl"],
        "releaseUrl": catalog["releaseUrl"],
        "japaneseAddon": addon,
        "job": job,
    }


def _safe_extract(archive: Path, staging: Path, expected: list[str]) -> None:
    expected_set = set(expected)
    with zipfile.ZipFile(archive) as bundle:
        files = {item.filename for item in bundle.infolist() if not item.is_dir()}
        if files != expected_set:
            raise RuntimeError("Rhubarbアーカイブの内容が配布カタログと一致しません。")
        for item in bundle.infolist():
            path = Path(item.filename)
            if path.is_absolute() or ".." in path.parts or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise RuntimeError("Rhubarbアーカイブに安全でない項目があります。")
        bundle.extractall(staging)


def _verify_architecture(executable: Path, key: str) -> None:
    header = executable.read_bytes()[:4096]
    if key == "darwin-arm64":
        if len(header) < 8 or header[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack("<I", header[4:8])[0] != 0x0100000C:
            raise RuntimeError("Rhubarb実行ファイルがmacOS arm64専用ではありません。")
        return
    if len(header) < 64 or header[:2] != b"MZ":
        raise RuntimeError("Rhubarb実行ファイルがWindows x64形式ではありません。")
    pe_offset = struct.unpack("<I", header[0x3C:0x40])[0]
    full_header = executable.read_bytes()[:pe_offset + 6]
    if full_header[pe_offset:pe_offset + 4] != b"PE\0\0" or struct.unpack("<H", full_header[pe_offset + 4:pe_offset + 6])[0] != 0x8664:
        raise RuntimeError("Rhubarb実行ファイルがWindows x64専用ではありません。")


def _self_test(executable: Path) -> None:
    version = subprocess.run([str(executable), "--version"], cwd=executable.parent, capture_output=True, timeout=15, check=False)
    if version.returncode != 0:
        raise RuntimeError("Rhubarbのバージョン確認に失敗しました。")
    with tempfile.TemporaryDirectory(prefix="scena-rhubarb-selftest-") as temporary:
        wav_path, output = Path(temporary) / "silence.wav", Path(temporary) / "result.json"
        with wave.open(str(wav_path), "wb") as writer:
            writer.setparams((1, 2, 16_000, 16_000 // 4, "NONE", "not compressed"))
            writer.writeframes(b"\0\0" * (16_000 // 4))
        completed = subprocess.run([str(executable), "-f", "json", "-r", "phonetic", "--extendedShapes", "X", "-o", str(output), str(wav_path)], cwd=executable.parent, capture_output=True, timeout=30, check=False)
        if completed.returncode != 0 or not output.is_file() or not isinstance(json.loads(output.read_text()).get("mouthCues"), list):
            raise RuntimeError("Rhubarbの音声解析self-testに失敗しました。")


def _download_progress(blocks: int, block_size: int, total: int) -> None:
    with INSTALL_LOCK:
        if not INSTALL_JOB:
            return
        if INSTALL_JOB.get("cancelRequested"):
            raise RuntimeError("Rhubarbの追加をキャンセルしました。")
        size = total if total > 0 else INSTALL_JOB.get("totalBytes", 0)
        downloaded = blocks * block_size
        INSTALL_JOB.update(downloadedBytes=min(downloaded, size) if size > 0 else downloaded,
                           totalBytes=size)


def _install_worker() -> None:
    global INSTALL_JOB
    catalog, key, entry = _entry()
    staging: Path | None = None
    try:
        if not key or not entry or not entry.get("available"):
            raise RuntimeError("この環境向けRhubarbはまだ配布されていません。")
        deps.RHUBARB_DOWNLOADS_ROOT.mkdir(parents=True, exist_ok=True)
        partial = deps.RHUBARB_DOWNLOADS_ROOT / f"{catalog['releaseId']}-{key}.zip.partial"
        url = entry.get("url") or f"{catalog['releaseUrl'].replace('/tag/', '/download/')}/{entry['archiveName']}"
        with INSTALL_LOCK:
            if INSTALL_JOB and INSTALL_JOB.get("cancelRequested"):
                raise RuntimeError("Rhubarbの追加をキャンセルしました。")
            INSTALL_JOB.update(state="downloading", message="Rhubarbをダウンロードしています…",
                               downloadedBytes=0, totalBytes=int(entry.get("archiveBytes", 0)))
        urllib.request.urlretrieve(url, partial, reporthook=_download_progress)
        with INSTALL_LOCK:
            if INSTALL_JOB and INSTALL_JOB.get("cancelRequested"):
                raise RuntimeError("Rhubarbの追加をキャンセルしました。")
            INSTALL_JOB.update(state="verifying", message="Rhubarbを検証しています…",
                               downloadedBytes=partial.stat().st_size)
        if _sha256(partial) != entry["archiveSha256"]:
            raise RuntimeError("RhubarbアーカイブのSHA-256が一致しません。")
        target = _runtime_dir(catalog, key)
        staging = target.parent / f".{target.name}-{uuid.uuid4().hex}.staging"
        staging.mkdir(parents=True)
        _safe_extract(partial, staging, list(entry["files"]))
        executable = staging / entry["executable"]
        if _sha256(executable) != entry["executableSha256"]:
            raise RuntimeError("Rhubarb実行ファイルのSHA-256が一致しません。")
        executable.chmod(executable.stat().st_mode | 0o100)
        with INSTALL_LOCK:
            if INSTALL_JOB:
                INSTALL_JOB.update(state="verifying", message="Rhubarbを検証しています…")
                if INSTALL_JOB.get("cancelRequested"):
                    raise RuntimeError("Rhubarbの追加をキャンセルしました。")
        _verify_architecture(executable, key)
        _self_test(executable)
        addon = verify_packaged_addon(executable, entry, key, _verify_architecture)
        with INSTALL_LOCK:
            if INSTALL_JOB.get('cancelRequested'):
                raise RuntimeError('Rhubarbの追加をキャンセルしました。')
        (staging / ".ready").write_text(json.dumps({"releaseId": catalog["releaseId"],
                                                  'archiveSha256': entry['archiveSha256'], 'japaneseAddon': addon, 'entry': entry}))
        replace_runtime(staging, target)
        remove_obsolete(deps.RHUBARB_RUNTIMES_ROOT, key, target)
        shutil.rmtree(deps.RHUBARB_CACHE_ROOT, ignore_errors=True)
        partial.unlink(missing_ok=True)
        with INSTALL_LOCK:
            INSTALL_JOB.update(state="complete", message="Rhubarbを追加しました。")
    except Exception as error:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        with INSTALL_LOCK:
            if INSTALL_JOB:
                INSTALL_JOB.update(state="cancelled" if INSTALL_JOB.get("cancelRequested") else "failed", message=str(error), error=str(error))


@deps.app.get("/api/lipsync/rhubarb")
def get_rhubarb_status() -> dict[str, Any]:
    return rhubarb_status()


@deps.app.post("/api/lipsync/rhubarb/install")
def install_rhubarb() -> dict[str, Any]:
    global INSTALL_JOB
    status = rhubarb_status()
    if not status["supported"] or not status["available"]:
        raise HTTPException(status_code=409, detail="この環境向けRhubarbはまだ配布されていません。")
    with INSTALL_LOCK:
        if INSTALL_JOB and INSTALL_JOB.get("state") in {"queued", "downloading", "verifying"}:
            raise HTTPException(status_code=409, detail="Rhubarbを追加中です。")
        INSTALL_JOB = {"id": uuid.uuid4().hex, "state": "queued", "message": "Rhubarbの追加を準備しています…", "cancelRequested": False}
        result = dict(INSTALL_JOB)
    threading.Thread(target=_install_worker, daemon=True).start()
    return result


@deps.app.post("/api/lipsync/rhubarb/install/cancel")
def cancel_rhubarb_install() -> dict[str, Any]:
    with INSTALL_LOCK:
        if not INSTALL_JOB or INSTALL_JOB.get("state") not in {"queued", "downloading", "verifying"}:
            raise HTTPException(status_code=409, detail="追加中のRhubarbはありません。")
        INSTALL_JOB["cancelRequested"] = True
        INSTALL_JOB["message"] = "キャンセルを受け付けました…"
        return dict(INSTALL_JOB)


@deps.app.delete("/api/lipsync/rhubarb")
def delete_rhubarb() -> dict[str, Any]:
    catalog, key, _entry_value = _entry()
    with INSTALL_LOCK:
        if INSTALL_JOB and INSTALL_JOB.get("state") in {"queued", "downloading", "verifying"}:
            raise HTTPException(status_code=409, detail="Rhubarbを追加中のため削除できません。")
    if key:
        remove_obsolete(deps.RHUBARB_RUNTIMES_ROOT, key)
    shutil.rmtree(deps.RHUBARB_CACHE_ROOT, ignore_errors=True)
    return rhubarb_status()


deps.register(__name__, ["rhubarb_executable", "rhubarb_status"])

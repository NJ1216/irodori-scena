from __future__ import annotations

from server.platform_support import require_builtin_llm

import json
import os
import re
import shutil
from server import subprocess_boundary as subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.modules.omlx_runtime_verification import activate_staging, runtime_fingerprint, runtime_import_probe
from server.modules.omlx_startup_probe import verify as _verify
from server.modules.omlx_registry_helpers import directory_size as _size, installed_omlx_version as _installed_version
from server.modules.omlx_registry_migration import _registry_runtime_key, migrate_registry, normalize_registry
from server.registry import deps
from server.modules.llm_runtime_binding import serialized

REPOSITORY, OMLX_VERSION, PYTHON_VERSION = "jundot/omlx", "0.6.4", "3.12"
BUSY = {"resolving", "downloading", "installing", "verifying", "cancelling"}
_LOCK = threading.RLock()
_JOB: dict[str, Any] = {"id": None, "runtimeId": None, "state": "idle", "message": ""}
_PROCESS: subprocess.Popen[str] | None = None
_CANCEL = threading.Event()


def _manifest() -> Path:
    return Path(os.getenv("SCENA_OMLX_REQUIREMENTS") or deps.PROJECT_ROOT / "tools/omlx-runtime-requirements.txt")


def _launcher() -> Path:
    return Path(os.getenv("SCENA_OMLX_LAUNCHER") or deps.PROJECT_ROOT / "tools/omlx-sidecar.py")


def _fingerprint() -> str:
    return runtime_fingerprint((_manifest(), _launcher()))


def _recommended_id() -> str:
    return f"scena-{_fingerprint()}"


def _base() -> Path:
    return deps.LOCAL_LLM_ROOT / "runtime"


def _registry_path() -> Path:
    return deps.LOCAL_LLM_ROOT / "runtime-registry.json"


def _runtime_path(runtime_id: str) -> Path:
    return _base() / f"omlx-{re.sub(r'[^a-zA-Z0-9._-]', '-', runtime_id).removeprefix('scena-')}"


def _manifest_versions() -> dict[str, str]:
    result = {}
    try:
        lines = _manifest().read_text(encoding="utf-8").splitlines()
    except OSError:
        return result
    for line in lines:
        if match := re.match(r"([\w-]+)==([^\s]+)$", line.strip()):
            result[match[1]] = match[2]
        elif match := re.match(r"omlx\s+@.+@([0-9a-f]{40})$", line.strip()):
            result["omlxCommit"] = match[1]
    return result


def runtime_catalog() -> list[dict[str, Any]]:
    versions = _manifest_versions()
    commit = versions.get("omlxCommit")
    return [
        {
            "id": _recommended_id(),
            "displayName": "SCENA動作確認版",
            "omlxVersion": OMLX_VERSION,
            "gitRef": commit,
            "commit": commit,
            "pythonVersion": PYTHON_VERSION,
            "mlxVersion": versions.get("mlx"),
            "mlxLmVersion": versions.get("mlx-lm"),
            "mlxVlmVersion": versions.get("mlx-vlm"),
            "compatibility": "このSCENA版で動作確認済み",
            "recommended": True,
        }
    ]


def _read_registry() -> dict[str, Any]:
    try:
        value = json.loads(_registry_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"version": 1, "activeRuntimeId": None, "runtimes": []}
    except (OSError, ValueError):
        return {"version": 1, "activeRuntimeId": None, "runtimes": []}


def _write_registry(value: dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _registry_runtime() -> SimpleNamespace:
    return SimpleNamespace(
        base=_base,
        recommended_id=_recommended_id,
        fingerprint=_fingerprint,
        installed_version=_installed_version,
        size=_size,
    )


def _normalize_registry(registry: dict[str, Any]) -> bool:
    return normalize_registry(registry, _registry_runtime())


def _migrate(registry: dict[str, Any]) -> bool:
    return migrate_registry(registry, _registry_runtime())


@serialized
def _registry() -> dict[str, Any]:
    registry = _read_registry()
    changed = _normalize_registry(registry)
    if _migrate(registry) or changed:
        _write_registry(registry)
    return registry


def omlx_runtimes_status() -> dict[str, Any]:
    registry = _registry()
    for item in registry["runtimes"]:
        if not isinstance(item.get("diskBytes"), int):
            item["diskBytes"] = _size(Path(item["path"]))
        if not (Path(item["path"]) / ".ready").is_file():
            item["state"] = "missing"
    with _LOCK:
        job = dict(_JOB)
    recommended = _recommended_id()
    active = registry.get("activeRuntimeId")
    return {
        "activeRuntimeId": active,
        "recommendedRuntimeId": recommended,
        "updateAvailable": bool(active and active != recommended),
        "catalog": runtime_catalog(),
        "installedRuntimes": registry["runtimes"],
        "job": job,
    }


def omlx_environment_root() -> Path:
    status = omlx_runtimes_status()
    active = status["activeRuntimeId"]
    item = next((x for x in status["installedRuntimes"] if x["id"] == active), None)
    return Path(item["path"]) if item else _runtime_path(_recommended_id())


def omlx_environment_python() -> Path:
    return omlx_environment_root() / "bin/python"


def omlx_environment_status() -> dict[str, Any]:
    status = omlx_runtimes_status()
    active = status["activeRuntimeId"]
    item = next((x for x in status["installedRuntimes"] if x["id"] == active), None)
    job = status["job"]
    ready = bool(item and item["state"] == "ready")
    state = "ready" if ready and job["state"] not in BUSY else job["state"]
    return {
        "state": state,
        "message": "oMLX実行基盤を利用できます。" if state == "ready" else job["message"],
        "ready": ready,
        "fingerprint": _fingerprint(),
    }


def _github(path: str) -> Any:
    base = os.getenv("SCENA_OMLX_GITHUB_API", "https://api.github.com").rstrip("/")
    request = urllib.request.Request(
        base + path, headers={"Accept": "application/vnd.github+json", "User-Agent": "irodori-scena"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def list_omlx_releases() -> list[dict[str, Any]]:
    try:
        releases = _github(f"/repos/{REPOSITORY}/releases?per_page=100")
    except (OSError, ValueError, urllib.error.HTTPError) as error:
        raise HTTPException(status_code=502, detail=f"GitHub Releasesを取得できませんでした: {error}") from error
    return [
        {
            "tag": x["tag_name"],
            "name": x.get("name") or x["tag_name"],
            "prerelease": bool(x.get("prerelease")),
            "publishedAt": x.get("published_at"),
        }
        for x in releases
        if isinstance(x, dict) and not x.get("draft") and x.get("tag_name")
    ]


def release_runtime_id(tag: str, commit: str) -> str:
    return f"release-{tag}-{commit[:12]}-{_fingerprint()}"


def _resolve_release(tag: str) -> tuple[dict[str, Any], str]:
    release = _github(f"/repos/{REPOSITORY}/releases/tags/{urllib.parse.quote(tag, safe='')}")
    if release.get("draft") or release.get("tag_name") != tag:
        raise HTTPException(422, "公開済みoMLX Releaseではありません。")
    target = _github(f"/repos/{REPOSITORY}/git/ref/tags/{urllib.parse.quote(tag, safe='')}").get("object", {})
    if target.get("type") == "tag":
        target = _github(f"/repos/{REPOSITORY}/git/tags/{target.get('sha')}").get("object", {})
    commit = str(target.get("sha", ""))
    if target.get("type") != "commit" or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise HTTPException(502, "Releaseのcommitを検証できませんでした。")
    return release, commit


def _set_job(**values: Any) -> None:
    global _JOB
    with _LOCK:
        _JOB = {**_JOB, **values}


def _check_cancel() -> None:
    if _CANCEL.is_set():
        raise InterruptedError("実行基盤の取得を取り消しました。")


def _run_install(spec: dict[str, Any]) -> None:
    global _PROCESS
    root = _runtime_path(spec["id"])
    staging = root.with_name(f".{root.name}.{_JOB['id']}.installing")
    try:
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=True)
        requirements = staging / "scena-requirements.txt"
        requirements.write_text(spec.get("resolvedRequirements") or spec.get("requirements") or _manifest().read_text())
        launcher = staging / "scena-launcher.py"
        launcher.write_text(spec.get("launcher") or _launcher().read_text())
        uv = os.getenv("SCENA_UV_EXECUTABLE", "uv")
        _set_job(state="resolving", message="Python実行環境を準備しています。")
        subprocess.run(
            [uv, "venv", "--allow-existing", "--python", spec.get("pythonVersion", PYTHON_VERSION), str(staging)],
            check=True,
            timeout=900,
        )
        _check_cancel()
        _set_job(state="downloading", message="oMLXと必要なライブラリを取得しています。")
        args = [uv, "pip", "install", "--python", str(staging / "bin/python")]
        args += (
            ["--no-deps", "-r", str(requirements)]
            if spec["source"] == "scena" or spec.get("resolvedRequirements")
            else [f"git+https://github.com/{REPOSITORY}.git@{spec['commit']}"]
        )
        with _LOCK:
            _PROCESS = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            process = _PROCESS
        output, _ = process.communicate(timeout=3600)
        if process.returncode:
            raise RuntimeError(
                output.strip().splitlines()[-1] if output.strip() else "oMLX実行基盤の取得に失敗しました。"
            )
        resolved = subprocess.run(
            [uv, "pip", "freeze", "--python", str(staging / "bin/python")],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        spec["resolvedRequirements"] = resolved.stdout
        _set_job(state="verifying", message="SCENAから起動できることを確認しています。")
        _check_cancel()
        _verify(staging, probe=spec["importProbe"])
        _check_cancel()
        (staging / ".ready").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        _activate_install(staging, root, spec)
    except Exception as error:
        shutil.rmtree(staging, ignore_errors=True)
        cancelled = _CANCEL.is_set()
        _set_job(state="cancelled" if cancelled else "failed", message=str(error), error=str(error))
    finally:
        with _LOCK:
            process, _PROCESS = _PROCESS, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


@serialized
def _activate_install(staging: Path, root: Path, spec: dict[str, Any]) -> None:
    _check_cancel()
    activate_staging(staging, root)
    installed = {
        **spec,
        "installSpec": dict(spec),
        "path": str(root),
        "omlxVersion": _installed_version(root) or spec.get("omlxVersion") or "不明",
        "verification": "verified",
        "state": "ready",
        "diskBytes": _size(root),
        "installedAt": time.time(),
        "error": None,
    }
    _publish_install(spec, installed)
    _set_job(state="complete", message="oMLX実行基盤を導入しました。")


@serialized
def _publish_install(spec: dict[str, Any], installed: dict[str, Any]) -> None:
    registry = _read_registry()
    _normalize_registry(registry)
    registry["runtimes"] = [x for x in registry["runtimes"] if x["id"] != spec["id"]] + [installed]
    _write_registry(registry)


@serialized
def install_omlx_runtime(tag: str | None = None, *, runtime_id: str | None = None) -> dict[str, Any]:
    global _JOB
    require_builtin_llm()
    with _LOCK:
        if _JOB["state"] in BUSY:
            raise HTTPException(409, "別のoMLX実行基盤を導入中です。")
    if not runtime_id and tag and tag.strip().removeprefix("v") == OMLX_VERSION:
        tag = None
    if tag:
        try:
            release, commit = _resolve_release(tag)
        except HTTPException:
            raise
        except (OSError, ValueError, urllib.error.HTTPError) as error:
            raise HTTPException(502, f"Releaseを検証できませんでした: {error}") from error
        spec = {
            "id": release_runtime_id(tag, commit),
            "displayName": release.get("name") or tag,
            "source": "github-release",
            "gitRef": tag,
            "commit": commit,
            "omlxVersion": tag,
        }
    else:
        spec = {**runtime_catalog()[0], "source": "scena"}
    installed = omlx_runtimes_status()["installedRuntimes"]
    if runtime_id and runtime_id != spec["id"]:
        saved = next((x for x in installed if x["id"] == runtime_id), None)
        if not saved or not saved.get("installSpec"):
            raise HTTPException(409, "この実行基盤の導入仕様がありません。別の版へ自動変更しません。")
        spec = saved["installSpec"]
    spec = {
        **spec,
        "requirements": spec.get("requirements") or _manifest().read_text(),
        "launcher": spec.get("launcher") or _launcher().read_text(),
        "pythonVersion": spec.get("pythonVersion") or PYTHON_VERSION,
        "importProbe": spec.get("importProbe")
        or (
            runtime_import_probe()
            if spec["source"] == "scena"
            else "import mlx.core,mlx_lm,mlx_vlm,omlx,fastapi,uvicorn"
        ),
    }

    if any(x["id"] == spec["id"] and x.get("state") == "ready" for x in installed):
        return omlx_runtimes_status()
    _CANCEL.clear()
    _JOB = {
        "id": f"runtime-{int(time.time() * 1000)}",
        "runtimeId": spec["id"],
        "state": "resolving",
        "message": "導入を準備しています。",
        "error": None,
    }
    registry = _registry()
    if not any(x["id"] == spec["id"] for x in registry["runtimes"]):
        registry["runtimes"].append(
            {
                **spec,
                "installSpec": dict(spec),
                "path": str(_runtime_path(spec["id"])),
                "state": "missing",
                "diskBytes": 0,
                "verification": "unverified",
            }
        )
        _write_registry(registry)
    threading.Thread(target=_run_install, args=(spec,), daemon=True).start()
    return omlx_runtimes_status()


@serialized
def cancel_omlx_environment_install() -> dict[str, Any]:
    from server.modules.model_runtime_jobs import active_jobs

    if active_jobs():
        raise HTTPException(409, "モデルが共有取得を待っています。モデル側の準備を取り消してください。")
    if _JOB["state"] not in BUSY:
        return omlx_runtimes_status()
    _CANCEL.set()
    _set_job(state="cancelling", message="oMLX実行基盤の導入を取り消しています。")
    with _LOCK:
        process = _PROCESS
    if process is not None and process.poll() is None:
        process.terminate()
    return omlx_runtimes_status()


def switch_omlx_runtime(runtime_id: str) -> dict[str, Any]:
    raise HTTPException(409, "モデル詳細の実行基盤から対象モデルだけを切り替えてください。")


@serialized
def delete_omlx_runtime(runtime_id: str) -> dict[str, Any]:
    registry = _registry()
    with _LOCK:
        if _JOB.get("runtimeId") == runtime_id and _JOB.get("state") in BUSY:
            raise HTTPException(409, "導入中のoMLX実行基盤は削除できません。")
    if (target := next((x for x in registry["runtimes"] if x["id"] == runtime_id), None)) is None:
        raise HTTPException(404, "oMLX実行基盤が見つかりません。")
    from server.modules.llm_runtime_binding import deletion_reason

    if reason := deletion_reason(runtime_id):
        raise HTTPException(409, reason)
    path = Path(target["path"])
    resolved_path = path.expanduser().resolve()
    shared_path = next(
        (
            item
            for index, item in enumerate(registry["runtimes"])
            if item.get("id") != runtime_id and _registry_runtime_key(item, index) == str(resolved_path)
        ),
        None,
    )
    if shared_path:
        raise HTTPException(
            409, "同じ実行基盤を別の登録が参照しているため削除できません。管理情報を再読み込みしてください。"
        )
    root = _base().resolve()
    if path.is_symlink() or resolved_path.parent != root or not path.name.startswith("omlx-"):
        raise HTTPException(422, "SCENA所有の実行基盤ディレクトリ以外は削除できません。")
    active = registry.get("activeRuntimeId") == runtime_id
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass
    except OSError as error:
        raise HTTPException(500, f"oMLX実行基盤を削除できませんでした: {error}") from error
    registry["runtimes"] = [x for x in registry["runtimes"] if x["id"] != runtime_id]
    if active:
        registry["activeRuntimeId"] = None
    _write_registry(registry)
    return omlx_runtimes_status()


def install_omlx_environment() -> dict[str, Any]:
    install_omlx_runtime()
    return omlx_environment_status()


deps.register(
    __name__,
    [
        "cancel_omlx_environment_install",
        "delete_omlx_runtime",
        "install_omlx_environment",
        "install_omlx_runtime",
        "list_omlx_releases",
        "omlx_environment_python",
        "omlx_environment_status",
        "omlx_runtimes_status",
        "runtime_catalog",
        "switch_omlx_runtime",
    ],
)

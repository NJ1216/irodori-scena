"""Per-card preparation. Cancelling a waiter never cancels a shared installation."""
from __future__ import annotations

import json
import threading
import time
import uuid
import sys
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps
from server.modules import omlx_environment as environments
from server.modules.llm_runtime_binding import LOCK, recommended_id, require_idle, runtime_item, serialized

JOBS: dict[str, dict[str, Any]] = {}
CANCEL: dict[str, threading.Event] = {}
TERMINAL = {"complete", "failed", "cancelled", "interrupted"}
INSTALL_LOCK = threading.Lock()
VERIFY_LOCK = threading.Lock()
_RESTORE_LOCK = threading.Lock()


def _path() -> Path:
    return deps.LOCAL_LLM_ROOT / "model-runtime-jobs.json"


def active_jobs(*, verifying_only: bool = False) -> list[dict[str, Any]]:
    return [x for x in JOBS.values() if (x["state"] not in TERMINAL or x.get("localBusy"))
            and (not verifying_only or x["state"] == "verifying" or x.get("localBusy"))]


def _persist() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(JOBS, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _restore() -> None:
    with _RESTORE_LOCK:
        _restore_once()


def _restore_once() -> None:
    if JOBS:
        return
    try:
        try:
            saved = json.loads(_path().read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            saved = json.loads(_path().read_text())
    except (OSError, ValueError):
        return
    restored, interrupted = {}, []
    for key, value in saved.items():
        if value["state"] not in TERMINAL:
            value.update(state="interrupted", message="アプリ終了で中断しました。再試行できます。")
            interrupted.append(key)
        value["localBusy"] = False
        restored[key] = value
    JOBS.update(restored)
    if sys.platform == "win32" and interrupted:
        # Resetting a test result writes the LLM registry under the runtime lock. A status read must not wait
        # for that lock (a TTS load holds it), and waiting for it inside _RESTORE_LOCK would invert the lock
        # order of start_model_runtime, so a busy lock moves the reset to its own thread.
        if LOCK.acquire(blocking=False):
            try:
                _reset_interrupted_tests(interrupted)
            finally:
                LOCK.release()
        else:
            threading.Thread(target=_reset_interrupted_tests, args=(interrupted,), daemon=True,
                             name="llm-interrupted-test-reset").start()


def _reset_interrupted_tests(card_ids: list[str]) -> None:
    for card_id in card_ids:
        deps.set_llm_test_status(card_id, {"state": "untested", "checkedAt": None, "errorCategory": None})


# A status read must not wait for the runtime lock, which a Windows TTS model load holds throughout.
def model_runtime_status(card: dict[str, Any]) -> dict[str, Any]:
    _restore()
    if sys.platform == "win32":
        metadata = card.get("localMetadata") or {}
        backend = str(metadata.get("backend") or deps.selected_backend())
        status = deps.llama_cpp_runtime_status(backend)
        return {"state": "ready" if status["ready"] else "missing", "runtimeId": card.get("runtimeId"),
                "version": status["version"], "recommended": backend == deps.recommended_backend(),
                "modelDownloadRequired": _model_download_required(card),
                "job": dict(JOBS[card["id"]]) if card["id"] in JOBS else None}
    job = JOBS.get(card["id"])
    installed = runtime_item(card.get("runtimeId", ""))
    initial_pending = job and job["previousRuntimeId"] == card.get("runtimeId") and job["state"] != "complete"
    return {"state": "ready" if installed and not initial_pending else "missing", "runtimeId": card.get("runtimeId"),
            "version": (installed or {}).get("omlxVersion"),
            "recommended": card.get("runtimeId") == recommended_id(),
            "modelDownloadRequired": _model_download_required(card), "job": dict(job) if job else None}


def _model_download_required(card: dict[str, Any]) -> bool:
    metadata = card.get("localMetadata") or {}
    if metadata.get("format") == "GGUF":
        return not metadata.get("files") or any(not Path(value).is_file() for value in metadata["files"])
    return bool(metadata.get("repoId") and not (Path(str(metadata.get("path", ""))) / ".scena-model.json").is_file())


def _resume_model(job: dict[str, Any]) -> None:
    if job.get("automatic"):
        return
    card = deps.resolve_llm_card(job["cardId"])
    if _model_download_required(card):
        deps.start_huggingface_download(card["localMetadata"]["repoId"], card["localMetadata"].get("variant"))


@serialized
def _update(job: dict[str, Any], **values: Any) -> None:
    job.update(**values)
    _persist()
    if sys.platform == "win32" and JOBS.get(job["cardId"]) is job and values.get("state") in {"failed", "cancelled"}:
        deps.set_llm_test_status(job["cardId"], {
            "state": "failed" if values["state"] == "failed" else "untested",
            "checkedAt": int(time.time() * 1000),
            "errorCategory": job.get("errorCategory") if values["state"] == "failed" else None})


_STAGE_LABELS = {
    "runtime_preparation": "実行基盤の準備",
    "model_download": "モデルデータの取得",
    "static_inspection": "モデルデータの検査",
    "model_loading": "モデルの起動",
    "completion": "短い応答確認",
    "schema_nonstream": "構造化応答確認",
    "schema_stream": "ストリーミング構造化応答確認",
}
_CATEGORY_LABELS = {
    "output_limit": "出力上限に達して本文が返りませんでした",
    "empty_response": "本文が返りませんでした",
    "timeout": "タイムアウトしました",
    "authentication": "認証に失敗しました",
    "files_missing": "必要なファイルが見つかりません",
    "memory_guard": "メモリ保護により起動できませんでした",
    "metal_oom": "メモリ不足が発生しました",
}


def _failure_details(job: dict[str, Any], error: BaseException) -> tuple[str, str]:
    from server.modules.llm_model_tests import _failure_category
    category = _failure_category(error)
    stage = str(job.get("stage") or "runtime_preparation")
    detail = _CATEGORY_LABELS.get(category) or " ".join(str(error).split()) or "処理に失敗しました"
    return category, f"{_STAGE_LABELS.get(stage, stage)}: {detail}"


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise InterruptedError("準備を取り消しました。モデルと以前の紐づけは保持されています。")


def _ensure(job: dict[str, Any], cancel: threading.Event) -> None:
    _update(job, stage="runtime_preparation")
    while not INSTALL_LOCK.acquire(timeout=0.1):
        _check_cancel(cancel)
    try:
        _check_cancel(cancel)
        if sys.platform == "win32":
            metadata = deps.resolve_llm_card(job["cardId"]).get("localMetadata") or {}
            status = deps.llama_cpp_runtime_status(metadata.get("backend"))
            if not status["ready"]:
                deps.install_llama_cpp_runtime(status["backend"])
            while True:
                status = deps.llama_cpp_runtime_status(status["backend"])
                if status["ready"]:
                    return
                state = status["job"].get("state")
                if state in {"failed", "cancelled"}:
                    raise RuntimeError(status["job"].get("error") or "llama.cppの準備に失敗しました。")
                _update(job, state="preparing", message="llama.cppを準備しています…")
                _check_cancel(cancel)
                cancel.wait(0.2)
        if runtime_item(job["runtimeId"]):
            return
        while environments._JOB["state"] in environments.BUSY:
            _check_cancel(cancel)
            cancel.wait(0.2)
        if runtime_item(job["runtimeId"]):
            return
        environments.install_omlx_runtime(job.get("tag"), runtime_id=job["runtimeId"])
        while environments._JOB["state"] in environments.BUSY:
            _update(job, state="preparing", message=environments._JOB["message"])
            _check_cancel(cancel)
            cancel.wait(0.2)
        _check_cancel(cancel)
        if not runtime_item(job["runtimeId"]):
            raise RuntimeError(environments._JOB.get("message") or "実行基盤の準備に失敗しました。")
    finally:
        INSTALL_LOCK.release()


def _wait_model(selected: dict[str, Any], job: dict[str, Any], cancel: threading.Event) -> None:
    _update(job, stage="model_download")
    while True:
        _check_cancel(cancel)
        from server.modules.huggingface_models import HF_DOWNLOADS
        downloads = [x for x in HF_DOWNLOADS.values() if x.get("cardId") == selected["cardId"]]
        current = deps.resolve_llm_card(job["cardId"])
        complete = not _model_download_required(current)
        if complete and (not downloads or downloads[-1]["state"] == "complete"):
            return
        if not downloads or downloads[-1]["state"] in {"failed", "cancelled"}:
            raise RuntimeError("モデルの取得が必要です。取得済みファイルは保持しています。")
        _update(job, state="waiting-model", message="モデルの取得完了を待っています。")
        cancel.wait(0.2)


def _reserve_verification(job: dict[str, Any], cancel: threading.Event) -> None:
    while True:
        _check_cancel(cancel)
        with LOCK:
            try:
                require_idle()
            except HTTPException:
                if not job.get("automatic"):
                    raise
            else:
                _update(job, state="verifying", localBusy=True, threadId=threading.get_ident(),
                        message="対象モデルの起動と短い生成を確認しています。")
                return
        _update(job, state="waiting-model", message="ローカル処理の完了を待っています。")
        cancel.wait(0.2)


def _verify_model(job: dict[str, Any], cancel: threading.Event) -> None:
    from server.modules import llm_model_tests as tests
    selected = deps.resolve_llm_card(job["cardId"])
    _wait_model(selected, job, cancel)
    # Download completion pins the concrete GGUF files in the registry.  Do not
    # inspect the snapshot captured while the transfer was still in progress.
    selected = deps.resolve_llm_card(job["cardId"])
    with VERIFY_LOCK:
        _reserve_verification(job, cancel)
        try:
            _update(job, stage="static_inspection")
            tests._static_inspection(selected)
            settings = dict(selected["settings"])
            if sys.platform == "win32":
                settings["backend"] = (selected.get("localMetadata") or {}).get("backend") or deps.selected_backend()
            _update(job, stage="model_loading")
            deps.load_local_llm(selected["model"], settings=settings, runtime_id=job["runtimeId"])
            selected["baseUrl"] = deps.local_llm_runtime_endpoint()
            selected["apiKey"] = deps.local_llm_runtime_api_key()
            _update(job, stage="completion")
            tests._completion(selected, cancel)
            capabilities = tests._local_model_capabilities(selected)
            _update(job, stage="schema_nonstream")
            nonstream = tests._schema_probe(selected, cancel, stream=False)
            _update(job, stage="schema_stream")
            streaming = tests._schema_probe(selected, cancel, stream=True)
            capabilities["structuredOutput"] = {
                "nonStreaming": nonstream,
                "streaming": streaming,
                "checkedAt": int(time.time() * 1000), "runtimeId": job["runtimeId"],
            }
            if selected["settings"].get("mtp"):
                engine = deps.local_llm_engine_status(selected["model"])
                if not engine.get("mtpActive"):
                    raise RuntimeError("この実行基盤でMTPを起動できませんでした。")
            _check_cancel(cancel)
            with LOCK:
                _check_cancel(cancel)
                registry = deps.read_llm_registry()
                card = next(x for x in registry["cards"] if x["id"] == job["cardId"])
                if card["runtimeId"] != job["previousRuntimeId"]:
                    raise RuntimeError("実行基盤の紐づけが変更されています。")
                card["runtimeId"] = job["runtimeId"]
                if sys.platform != "win32":
                    card["localMetadata"]["omlxVersion"] = job["runtimeId"]
                card["testStatus"] = {"state": "passed", "checkedAt": int(time.time() * 1000),
                                      "errorCategory": None, "runtimeId": job["runtimeId"]}
                card["capabilities"] = capabilities
                card["lastProbe"] = None
                deps.write_llm_registry(registry)
                _update(job, state="complete", stage="complete", errorCategory=None, message="モデルを使用できます。")
        finally:
            try:
                deps.stop_local_llm()
            finally:
                _update(job, localBusy=False)


def _run(job: dict[str, Any], cancel: threading.Event) -> None:
    try:
        _check_cancel(cancel)
        _resume_model(job)
        _ensure(job, cancel)
        _verify_model(job, cancel)
    except InterruptedError as error:
        _update(job, state="cancelled", stage="cancelled", errorCategory=None, message=str(error))
    except Exception as error:
        category, message = _failure_details(job, error)
        _update(job, state="failed", errorCategory=category, message=message)


@serialized
def start_model_runtime(card_id: str, runtime_id: str | None = None, tag: str | None = None, *, automatic: bool = False) -> dict[str, Any]:
    _restore()
    selected = deps.resolve_llm_card(card_id)
    if selected["source"] not in {"managed", "external"}:
        raise HTTPException(422, "外部接続にはoMLX実行基盤を設定できません。")
    if any(x["cardId"] == card_id for x in active_jobs()):
        raise HTTPException(409, "このモデルの実行基盤を準備中です。")
    if not automatic:
        require_idle()
    if runtime_id and tag:
        raise HTTPException(422, "版または導入済み基盤を1つ選択してください。")
    if sys.platform == "win32" and tag:
        raise HTTPException(422, "Windowsではllama.cppランタイムの版を個別指定できません。")
    if tag:
        release, commit = environments._resolve_release(tag)
        runtime_id = environments.release_runtime_id(tag, commit)
        del release
    runtime_id = runtime_id or selected["runtimeId"]
    if sys.platform != "win32" and not tag and runtime_id != recommended_id() and not runtime_item(runtime_id):
        saved = next((x for x in environments._registry()["runtimes"] if x["id"] == runtime_id), None)
        if not saved or not saved.get("installSpec"):
            raise HTTPException(409, "記録された実行基盤が欠損し、導入仕様もありません。詳細から版を選択してください。")
    job = {"id": uuid.uuid4().hex, "cardId": card_id, "runtimeId": runtime_id,
           "previousRuntimeId": selected["runtimeId"], "tag": tag, "automatic": automatic,
           "state": "preparing", "stage": "runtime_preparation", "errorCategory": None,
           "message": "実行基盤を準備しています。"}
    cancel = threading.Event()
    JOBS[card_id], CANCEL[card_id] = job, cancel
    if sys.platform == "win32":
        deps.set_llm_test_status(card_id, {"state": "testing", "checkedAt": None, "errorCategory": None})
    _persist()
    threading.Thread(target=_run, args=(job, cancel), daemon=True).start()
    return dict(job)


@serialized
def cancel_model_runtime(card_id: str) -> dict[str, Any]:
    if card_id not in CANCEL or not any(x["cardId"] == card_id for x in active_jobs()):
        raise HTTPException(409, "取消できる準備はありません。")
    CANCEL[card_id].set()
    return dict(JOBS[card_id])

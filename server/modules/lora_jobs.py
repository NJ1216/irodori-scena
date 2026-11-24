"""Durable owned training jobs; cancelled/partial checkpoints are never assets."""
from __future__ import annotations
import atexit
import json
import math
import os
from pathlib import Path
import signal
from server import subprocess_boundary as subprocess
import threading
import time
import uuid
from fastapi import HTTPException
from server.modules.lora_assets import import_adapter
from server.modules.lora_continuation import freeze_adapter
from server.modules.lora_inputs import freeze_rows
from server.modules.lora_runtime import PRESETS, training_runtime
from server.modules.lora_storage import lora_root, owned_path, read_record, write_json
from server.modules.lora_resource_guard import reserve_training, release_training

_LOCK = threading.RLock()
_PROCESSES: dict[str, subprocess.Popen] = {}
_TERMINAL = {"completed", "cancelled", "interrupted", "failed"}


def _settings(mode: str, supplied: dict) -> dict:
    if mode not in PRESETS:
        raise HTTPException(422, "学習モードが不正です。")
    if set(supplied) - set(PRESETS[mode]):
        raise HTTPException(422, "未対応の詳細設定です。")
    settings = {**PRESETS[mode], **supplied}
    bounds = {"maxSteps": (1, 100000), "batchSize": (1, 4), "learningRate": (1e-7, 0.01), "maxSeconds": (1, 120)}
    for key, (lower, upper) in bounds.items():
        value = settings[key]
        if key == "maxSeconds" and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
            raise HTTPException(422, f"詳細設定 {key} の値が不正です。")
        if key in {"maxSteps", "batchSize"} and type(value) is not int:
            raise HTTPException(422, f"詳細設定 {key} は整数で入力してください。")
    return settings


def _update(identifier: str, **changes) -> dict:
    with _LOCK:
        record = read_record("jobs", identifier)
        record.update(changes, updatedAt=int(time.time() * 1000))
        write_json(owned_path("jobs", identifier) / "record.json", record)
        return record


def get_job(identifier: str) -> dict:
    with _LOCK:
        record = read_record("jobs", identifier)
        if record["status"] not in _TERMINAL and record.get("ownerPid") != os.getpid():
            record = _update(identifier, status="interrupted", error="アプリ終了により学習が中断されました。途中成果は登録されていません。")
        return {key: value for key, value in record.items() if key not in {"ownerPid", "startedMonotonic"}}


def list_jobs() -> list[dict]:
    return [get_job(path.parent.name) for path in sorted((lora_root() / "jobs").glob("*/record.json"))]


def start_job(request: dict) -> dict:
    identifier = uuid.uuid4().hex
    settings = _settings(request.get("mode", "check"), request.get("settings") or {})
    if not str(request.get("name", "")).strip():
        raise HTTPException(422, "LoRA の管理名を入力してください。")
    reserve_training(identifier)
    directory = owned_path("jobs", identifier)
    try:
        runtime = training_runtime(verify=True)
        started = time.monotonic()
        directory.mkdir(parents=True)
        rows = freeze_rows(request["datasetId"], request["rows"], directory, max_seconds=settings["maxSeconds"])
        duration_mode = "automatic" if settings["maxSeconds"] is None else "explicit"
        if settings["maxSeconds"] is None:
            # Reference sampler requires a one-second lower bound; input PCM
            # and every prepared latent frame remain unchanged.
            settings["maxSeconds"] = max(1.0, max(row["durationSeconds"] for row in rows))
        frozen = {"rows": rows, "settings": settings, "runtime": runtime}
        if request.get("sourceAdapterId"):
            frozen["sourceAdapter"] = freeze_adapter(request["sourceAdapterId"], directory, runtime)
        write_json(directory / "request.json", frozen)
        record = {"id": identifier, "name": request["name"], "memo": request.get("memo", ""),
                  "sourceAdapterId": request.get("sourceAdapterId"),
                  "status": "queued", "stage": "queued", "step": 0, "totalSteps": settings["maxSteps"],
                  "error": None, "adapterId": None, "createdAt": int(time.time() * 1000),
                  "ownerPid": os.getpid(), "startedMonotonic": started, "durationMode": duration_mode, "mode": request.get("mode", "check"), "settings": settings}
        write_json(directory / "record.json", record)
        thread = threading.Thread(target=_run, args=(identifier, runtime), daemon=True, name=f"lora-{identifier[:8]}")
        thread.start()
        return get_job(identifier)
    except Exception:
        release_training(identifier)
        raise


def _run(identifier: str, runtime: dict) -> None:
    directory = owned_path("jobs", identifier)
    environment = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", PYTHONUNBUFFERED="1")
    environment.pop("PYTORCH_ENABLE_MPS_FALLBACK", None)
    try:
        with _LOCK:
            if read_record("jobs", identifier)["status"] == "cancelling":
                _update(identifier, status="cancelled", stage="cancelled")
                return
            _update(identifier, status="running", stage="preparing")
        command = [runtime["pythonPath"], str(Path(__file__).resolve().parents[1] / "lora_training_worker.py"),
                   "--job-dir", str(directory), "--owner-pid", str(os.getpid())]
        with _LOCK:
            if read_record("jobs", identifier)["status"] == "cancelling":
                _update(identifier, status="cancelled")
                return
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       cwd=runtime["enginePath"], env=environment, start_new_session=True,
                                       text=True, encoding="utf-8", errors="replace")
            _PROCESSES[identifier] = process
        _consume(identifier, process, directory)
        code = process.wait()
        with _LOCK:
            record = read_record("jobs", identifier)
            if record["status"] == "cancelling":
                _update(identifier, status="cancelled", stage="cancelled")
            elif code != 0 or record["step"] != record["totalSteps"]:
                _update(identifier, status="failed", stage="failed", error=f"学習が完了しませんでした (exit {code})。ログを確認してください。")
            else:
                asset = import_adapter(str(directory / "training/checkpoint_final"), record["name"], record["memo"])
                _update(identifier, status="completed", stage="completed", adapterId=asset["id"], adapter=asset,
                        elapsedSeconds=time.monotonic() - record.get("startedMonotonic", time.monotonic()))
    except Exception as error:
        _update(identifier, status="failed", stage="failed", error=str(getattr(error, "detail", error))[-1600:])
    finally:
        with _LOCK:
            owned = _PROCESSES.get(identifier)
        if owned is not None and owned.poll() is None:
            _terminate(owned)
        with _LOCK:
            _PROCESSES.pop(identifier, None)
        release_training(identifier)


def _consume(identifier: str, process, directory: Path):
    with (directory / "training.log").open("w", encoding="utf-8") as log:
        for line in process.stdout:
            log.write(line)
            log.flush()
            if not line.startswith("SCENA_PROGRESS "):
                continue
            try:
                event = json.loads(line.removeprefix("SCENA_PROGRESS "))
                allowed = {key: value for key, value in event.items() if key in {"stage", "step", "loss", "prepared", "inputCount"}}
                _update(identifier, **allowed)
            except (ValueError, TypeError):
                continue


def _terminate(process):
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # The child may have exited concurrently; still reap it below.
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass  # Natural exit or another owned cancellation won the race.
        process.wait(timeout=5)


def cancel_job(identifier: str) -> dict:
    with _LOCK:
        record = get_job(identifier)
        if record["status"] in _TERMINAL or record["status"] == "cancelling":
            return record
        _update(identifier, status="cancelling")
        process = _PROCESSES.get(identifier)
        if process:
            threading.Thread(target=_terminate, args=(process,), daemon=True).start()
        return get_job(identifier)


def shutdown_jobs():
    with _LOCK:
        processes = list(_PROCESSES.values())
    for process in processes:
        try:
            _terminate(process)
        except (OSError, subprocess.TimeoutExpired):
            pass


atexit.register(shutdown_jobs)

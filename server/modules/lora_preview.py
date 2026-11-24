"""Ephemeral audition jobs: captured references and drafts never become Takes."""
from __future__ import annotations

import atexit
import copy
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from server.modules.constants import VOICE_SAMPLE_TEXT
from server.modules.lora_mix import LoraMix, resolve_mix
from server.modules.request_model import StrictRequestModel
from server.scena_mlx_lora import supports_lora_model
from server.registry import deps

DEFAULT_SAMPLE_TEXT = VOICE_SAMPLE_TEXT
LOCK = threading.RLock()
JOBS: dict[str, dict] = {}
TTL = 3600


class PreviewSettings(StrictRequestModel):
    quality: Literal["turbo", "fast", "quality"]
    steps: int = Field(ge=1, le=1000)
    speechRate: float = Field(ge=0.5, le=2)
    textCfg: float = Field(ge=0, le=100)
    voiceCfg: float = Field(ge=0, le=100)
    captionCfg: float = Field(ge=0, le=100)


class PreviewRequest(StrictRequestModel):
    characterId: str
    referenceVersion: int = Field(ge=0)
    loraMix: LoraMix
    settings: PreviewSettings


class PreviewJob(StrictRequestModel):
    id: str
    status: Literal["generating", "completed", "cancelled", "failed"]
    audioUrl: str | None = None
    error: str | None = None


def _purge():
    terminal = sorted((job for job in JOBS.values() if job["status"] != "generating"), key=lambda job: job["created"])
    evict = {job["id"] for job in terminal[:-32]}
    for identifier, job in list(JOBS.items()):
        if job["status"] != "generating" and (time.monotonic() - job["created"] > TTL or identifier in evict):
            shutil.rmtree(job["root"], ignore_errors=True)
            del JOBS[identifier]


def _public(job):
    return {key: job[key] for key in ("id", "status", "audioUrl", "error")}


def start_preview(request: PreviewRequest):
    deps.require_tts_available()
    runtime = copy.deepcopy(deps.selected_tts_runtime())
    if not supports_lora_model((runtime or {}).get("model") or {}):
        raise HTTPException(409, "試聴は固定版v4.1 Smallの非量子化MLX FP16／FP32で利用できます。")
    with LOCK, deps.PROJECT_ROOT_LOCK:
        _purge()
        if any(job["status"] == "generating" for job in JOBS.values()):
            raise HTTPException(409, "試聴を生成中です。完了またはキャンセル後に再試行してください。")
        character = deps.find_character(deps.read_project(), request.characterId)
        if int(character.get("referenceVersion", 0)) != request.referenceVersion:
            raise HTTPException(409, "参照音声が変更されました。キャストを開き直してください。")
        reference = Path(str(character.get("referenceFile", "")))
        if not reference.is_file():
            raise HTTPException(422, "参照音声が見つかりません。")
        adapter = resolve_mix(request.loraMix.model_dump())
        root = Path(tempfile.mkdtemp(prefix="scena-audition-"))
        try:
            shutil.copyfile(reference, root / "reference.wav")
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        identifier = deps.new_id("audition")
        job = {"id": identifier, "status": "generating", "audioUrl": None, "error": None,
               "root": root, "cancel": threading.Event(), "created": time.monotonic()}
        JOBS[identifier] = job
        text = str(character.get("sampleText") or "").strip() or DEFAULT_SAMPLE_TEXT
        launch_preview(job, text, request.settings.model_dump(), adapter, runtime)
        return _public(job)


def launch_preview(*args):
    thread = threading.Thread(target=_run, args=args, daemon=True)
    args[0]["thread"] = thread
    thread.start()


def _run(job, text, settings, adapter, runtime):
    output = job["root"] / "preview.wav"
    try:
        if job["cancel"].is_set():
            return
        if runtime != deps.selected_tts_runtime():
            raise ValueError("音声モデル設定が変更されました。もう一度試聴してください。")
        deps.run_irodori(text=text, caption=None, output=output, seed=0,
                         ref_wav=job["root"] / "reference.wav", quality=settings["quality"],
                         generation_settings={**settings, "speechRate": 1.0}, lora_adapter=adapter,
                         should_cancel=job["cancel"].is_set)
        deps.validate_take_wav(output)
        with LOCK:
            if not job["cancel"].is_set():
                job.update(status="completed", audioUrl=f"/api/lora/previews/{job['id']}/audio")
    except Exception as error:
        with LOCK:
            if not job["cancel"].is_set():
                detail = error.detail if isinstance(error, HTTPException) else str(error)
                job.update(status="failed", error=str(detail))
    finally:
        with LOCK:
            if job["cancel"].is_set():
                job.update(status="cancelled", audioUrl=None)
            if job["status"] != "completed":
                shutil.rmtree(job["root"], ignore_errors=True)
            else:
                (job["root"] / "reference.wav").unlink(missing_ok=True)


def get_preview(identifier):
    with LOCK:
        _purge()
        job = JOBS.get(identifier)
        if job is None:
            raise HTTPException(404, "試聴音声の有効期限が切れました。")
        return job


@deps.app.post("/api/lora/previews", response_model=PreviewJob)
def preview_start(request: PreviewRequest):
    return start_preview(request)


@deps.app.get("/api/lora/previews/{identifier}", response_model=PreviewJob)
def preview_status(identifier: str):
    with LOCK:
        return _public(get_preview(identifier))


@deps.app.post("/api/lora/previews/{identifier}/cancel", response_model=PreviewJob)
def preview_cancel(identifier: str):
    with LOCK:
        job = get_preview(identifier)
        job["cancel"].set()
        if job["status"] != "generating":
            shutil.rmtree(job["root"], ignore_errors=True)
            job.update(status="cancelled", audioUrl=None)
        return _public(job)


@deps.app.get("/api/lora/previews/{identifier}/audio")
def preview_audio(identifier: str):
    with LOCK:
        job = get_preview(identifier)
        if job["status"] != "completed":
            raise HTTPException(409, "試聴音声はまだ利用できません。")
        return FileResponse(job["root"] / "preview.wav", media_type="audio/wav", headers={"Cache-Control": "no-store"})

@deps.app.on_event("shutdown")
def shutdown_previews():
    with LOCK:
        jobs = list(JOBS.values())
        for job in jobs:
            job["cancel"].set()
    for job in jobs:
        thread = job.get("thread")
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        shutil.rmtree(job["root"], ignore_errors=True)


atexit.register(shutdown_previews)

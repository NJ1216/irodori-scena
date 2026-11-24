"""LoRA review, device assets and managed training HTTP boundary."""
from __future__ import annotations
from typing import Annotated, Any, Literal
from fastapi import Query
from fastapi.responses import FileResponse
from pydantic import Field
from server.modules.request_model import StrictRequestModel
from server.modules.lora_assets import import_adapter, list_adapters
from server.modules.lora_asset_lifecycle import adapter_usage, archive_adapter, restore_adapter, update_adapter, delete_adapter
from server.modules.lora_inputs import stage_inputs, input_audio_path
from server.modules.lora_folder_inputs import stage_folder
from server.modules.lora_jobs import cancel_job, get_job, list_jobs, start_job, shutdown_jobs
from server.modules.lora_runtime import lora_status, MODEL_REPO, MODEL_REVISION
from server.registry import deps


class InputFile(StrictRequestModel):
    name: str = Field(min_length=1, max_length=500)
    dataBase64: str


class InputRequest(StrictRequestModel):
    files: list[InputFile] = Field(min_length=1, max_length=500)


class FolderInputRequest(StrictRequestModel):
    path: str = Field(min_length=1, max_length=8000)


class InputRow(StrictRequestModel):
    id: str
    text: str = Field(default="", max_length=10000)
    caption: str = Field(default="", max_length=10000)
    speakerId: str = Field(default="", max_length=200)
    excluded: bool = False


class TrainingRequest(StrictRequestModel):
    datasetId: str
    sourceAdapterId: str | None = Field(default=None, min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    memo: str = Field(default="", max_length=10000)
    mode: Literal["check", "normal"] = "check"
    rows: list[InputRow] = Field(min_length=1, max_length=500)
    settings: dict[str, Any] | None = None


class ImportRequest(StrictRequestModel):
    path: str = Field(min_length=1, max_length=8000)
    name: str = Field(min_length=1, max_length=200)
    memo: str = Field(default="", max_length=10000)
    baseModelRepo: str = MODEL_REPO
    baseModelRevision: str = MODEL_REVISION


class AdapterUpdateRequest(StrictRequestModel):
    name: str = Field(min_length=1, max_length=200)
    memo: str = Field(default="", max_length=10000)


@deps.app.patch("/api/lora/adapters/{adapter_id}")
def edit_adapter(adapter_id: str, request: AdapterUpdateRequest):
    return update_adapter(adapter_id, request.name, request.memo)


@deps.app.get("/api/lora/status")
def status():
    return lora_status()


@deps.app.post("/api/lora/inputs")
def inputs(request: InputRequest):
    return stage_inputs([file.model_dump() for file in request.files])


@deps.app.post("/api/lora/inputs/folder")
def folder_inputs(request: FolderInputRequest):
    return stage_folder(request.path)


@deps.app.get("/api/lora/inputs/{dataset_id}/rows/{row_id}/audio")
def input_audio(dataset_id: str, row_id: str):
    return FileResponse(input_audio_path(dataset_id, row_id), media_type="audio/wav", headers={"Cache-Control": "no-store"})


@deps.app.get("/api/lora/jobs")
def jobs():
    return list_jobs()


@deps.app.post("/api/lora/jobs")
def start(request: TrainingRequest):
    return start_job(request.model_dump())


@deps.app.get("/api/lora/jobs/{job_id}")
def job(job_id: str):
    return get_job(job_id)


@deps.app.post("/api/lora/jobs/{job_id}/cancel")
def cancel(job_id: str):
    return cancel_job(job_id)


@deps.app.get("/api/lora/adapters")
def adapters(include_archived: Annotated[bool, Query(alias="includeArchived")] = False):
    return list_adapters(include_archived=include_archived)


@deps.app.get("/api/lora/adapters/archived")
def archived_adapters():
    return list_adapters(archived=True)


@deps.app.get("/api/lora/adapters/{adapter_id}/usage")
def usage(adapter_id: str):
    return adapter_usage(adapter_id)


@deps.app.delete("/api/lora/adapters/{adapter_id}")
def remove_adapter(adapter_id: str):
    return delete_adapter(adapter_id)


@deps.app.post("/api/lora/adapters/{adapter_id}/archive")
def archive(adapter_id: str):
    return archive_adapter(adapter_id)


@deps.app.post("/api/lora/adapters/{adapter_id}/restore")
def restore(adapter_id: str):
    return restore_adapter(adapter_id)


@deps.app.post("/api/lora/adapters/import")
def add_adapter(request: ImportRequest):
    return import_adapter(request.path, request.name, request.memo,
                          base_model_repo=request.baseModelRepo, base_model_revision=request.baseModelRevision)


@deps.app.on_event("shutdown")
def shutdown():
    shutdown_jobs()

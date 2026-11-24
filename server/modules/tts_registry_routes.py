from __future__ import annotations

from typing import Any
from pydantic import Field
from server.modules.request_model import StrictRequestModel
from server.registry import deps


class TtsSelectionRequest(StrictRequestModel):
    engine_id: str | None = Field(default=None, max_length=8000)
    model_id: str | None = Field(default=None, max_length=8000)


class TtsVariantRequest(StrictRequestModel):
    variant_id: str = Field(min_length=1, max_length=120)


class ExternalEngineRequest(StrictRequestModel):
    path: str = Field(min_length=1, max_length=8000)


class LibraryScanRequest(StrictRequestModel):
    path: str = Field(min_length=1, max_length=8000)


class LibraryRequest(StrictRequestModel):
    root: str = Field(min_length=1, max_length=8000)
    engine_path: str = Field(min_length=1, max_length=8000)
    display_name: str | None = Field(default=None, max_length=200)


class LibraryModelRequest(StrictRequestModel):
    model_path: str = Field(min_length=1, max_length=8000)
    codec_path: str = Field(min_length=1, max_length=8000)


@deps.app.get("/api/tts/catalog")
def get_tts_catalog() -> dict[str, Any]:
    return deps.tts_catalog()


@deps.app.get("/api/tts/registry")
def get_tts_registry() -> dict[str, Any]:
    return deps.tts_registry_view()


@deps.app.get("/api/tts/runtime/status")
def get_tts_runtime_status() -> dict[str, Any]:
    return deps.tts_runtime_status()


@deps.app.post("/api/tts/runtime/prepare")
def prepare_tts_runtime() -> dict[str, Any]:
    return deps.start_tts_prepare()


@deps.app.put("/api/tts/defaults")
def update_tts_defaults(request: TtsSelectionRequest) -> dict[str, Any]:
    result = deps.set_tts_defaults(request.engine_id, request.model_id)
    deps.start_tts_prepare()
    return result


@deps.app.put("/api/project/tts-selection")
def update_project_tts_selection(request: TtsSelectionRequest) -> dict[str, Any]:
    result = deps.set_project_tts_selection(request.engine_id, request.model_id)
    deps.start_tts_prepare()
    return result


@deps.app.put("/api/tts/models/{model_id:path}/active-variant")
def update_tts_active_variant(model_id: str, request: TtsVariantRequest) -> dict[str, Any]:
    result = deps.set_tts_active_variant(model_id, request.variant_id)
    deps.start_tts_prepare()
    return result


@deps.app.post("/api/tts/models/{model_id:path}/variants/{variant_id}/downloads")
def start_tts_variant_download(model_id: str, variant_id: str) -> dict[str, Any]:
    return deps.start_tts_variant_install(model_id, variant_id)


@deps.app.delete("/api/tts/models/{model_id:path}/variants/{variant_id}")
def remove_tts_variant(model_id: str, variant_id: str) -> dict[str, Any]:
    return deps.delete_tts_variant(model_id, variant_id)


@deps.app.post("/api/tts/external-engines")
def add_external_engine(request: ExternalEngineRequest) -> dict[str, Any]:
    return deps.register_external_engine(request.path)


@deps.app.post("/api/tts/libraries/scan")
def scan_tts_library(request: LibraryScanRequest) -> dict[str, Any]:
    return deps.scan_tts_library(request.path)


@deps.app.post("/api/tts/libraries")
def add_tts_library(request: LibraryRequest) -> dict[str, Any]:
    return deps.register_tts_library(request.root, request.engine_path, request.display_name)


@deps.app.delete("/api/tts/libraries/{library_id}")
def remove_tts_library(library_id: str) -> dict[str, Any]:
    return deps.disconnect_tts_library(library_id)


@deps.app.post("/api/tts/libraries/{library_id}/models")
def register_tts_library_model(library_id: str, request: LibraryModelRequest) -> dict[str, Any]:
    return deps.start_library_model_registration(library_id, request.model_path, request.codec_path)


@deps.app.get("/api/tts/library-model-jobs/{job_id}")
def get_tts_library_model_job(job_id: str) -> dict[str, Any]:
    return deps.library_model_job(job_id)


@deps.app.post("/api/tts/library-model-jobs/{job_id}/cancel")
def cancel_tts_library_model_job(job_id: str) -> dict[str, Any]:
    return deps.cancel_library_model_job(job_id)


@deps.app.post("/api/tts/{kind}/{asset_id:path}/downloads")
def start_tts_download(kind: str, asset_id: str) -> dict[str, Any]:
    return deps.start_tts_install(kind, asset_id)


@deps.app.post("/api/tts/{kind}/{asset_id:path}/verify")
def verify_tts_install(kind: str, asset_id: str) -> dict[str, Any]:
    return deps.verify_tts_asset(kind, asset_id)


@deps.app.get("/api/tts/downloads/{job_id}")
def get_tts_download(job_id: str) -> dict[str, Any]:
    return deps.tts_install_status(job_id)


@deps.app.post("/api/tts/downloads/{job_id}/cancel")
def cancel_tts_download(job_id: str) -> dict[str, Any]:
    return deps.cancel_tts_install(job_id)


@deps.app.delete("/api/tts/{kind}/{asset_id:path}")
def remove_tts_asset(kind: str, asset_id: str) -> dict[str, Any]:
    return deps.delete_tts_asset(kind, asset_id)

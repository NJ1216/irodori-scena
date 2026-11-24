from __future__ import annotations

import json
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps


@deps.app.get("/api/llm/registry")
def get_llm_registry() -> dict[str, Any]:
    return deps.public_llm_registry()


@deps.app.post("/api/llm/endpoints")
def add_llm_endpoint(options: dict[str, Any]) -> dict[str, Any]:
    return deps.create_remote_llm_endpoint(options)


@deps.app.post("/api/llm/cards")
def add_llm_card(options: dict[str, Any]) -> dict[str, Any]:
    return deps.create_remote_llm_card(options)


@deps.app.post("/api/llm/remote/models")
def inspect_remote_models(options: dict[str, Any]) -> dict[str, Any]:
    return {"models": deps.inspect_remote_llm_models(options)}


@deps.app.post("/api/llm/remote/settings")
def add_remote_setting(options: dict[str, Any]) -> dict[str, Any]:
    return deps.create_remote_llm_setting(options)


@deps.app.get("/api/llm/endpoints/{endpoint_id}/models")
def discover_endpoint_models(endpoint_id: str) -> dict[str, Any]:
    return {"models": deps.discover_llm_endpoint_models(endpoint_id)}


@deps.app.put("/api/llm/endpoints/{endpoint_id}/credential")
def save_endpoint_credential(endpoint_id: str, options: dict[str, Any]) -> dict[str, Any]:
    return deps.save_llm_endpoint_credential(endpoint_id, str(options.get("credential", "")))


@deps.app.delete("/api/llm/endpoints/{endpoint_id}/credential")
def remove_endpoint_credential(endpoint_id: str) -> dict[str, Any]:
    return deps.delete_llm_endpoint_credential(endpoint_id)


@deps.app.delete("/api/llm/endpoints/{endpoint_id}")
def remove_llm_endpoint(endpoint_id: str) -> dict[str, Any]:
    return deps.delete_llm_endpoint(endpoint_id)


@deps.app.put("/api/llm/cards/{card_id}/default")
def choose_default_llm_card(card_id: str) -> dict[str, Any]:
    return deps.set_default_llm_card(card_id)


@deps.app.patch("/api/llm/cards/{card_id}")
def edit_llm_card(card_id: str, options: dict[str, Any]) -> dict[str, Any]:
    return deps.update_llm_card(card_id, options)


@deps.app.post("/api/llm/cards/{card_id}/tests")
def test_llm_card(card_id: str) -> dict[str, Any]:
    return deps.start_llm_model_test(card_id)


@deps.app.get("/api/llm/tests/{job_id}")
def get_llm_card_test(job_id: str) -> dict[str, Any]:
    return deps.llm_model_test_status(job_id)


@deps.app.post("/api/llm/tests/{job_id}/cancel")
def cancel_llm_card_test(job_id: str) -> dict[str, Any]:
    return deps.cancel_llm_model_test(job_id)


@deps.app.delete("/api/llm/cards/{card_id}")
def remove_llm_card(card_id: str) -> dict[str, Any]:
    return deps.delete_llm_card(card_id)


@deps.app.get("/api/llm/huggingface/token")
def get_huggingface_token_status() -> dict[str, bool]:
    return deps.huggingface_token_status()


@deps.app.put("/api/llm/huggingface/token")
def save_huggingface_token(options: dict[str, Any]) -> dict[str, bool]:
    return deps.set_huggingface_token(str(options.get("token", "")))


@deps.app.get("/api/llm/huggingface/search")
def find_huggingface_models(q: str = "", filters: str = "[]", order: str = "downloads") -> dict[str, Any]:
    try:
        selected = json.loads(filters)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="検索タグが不正です。") from error
    if not isinstance(selected, list) or not all(isinstance(value, str) for value in selected):
        raise HTTPException(status_code=422, detail="検索タグが不正です。")
    return deps.search_huggingface_models(q, selected, order)


@deps.app.post("/api/llm/huggingface/metadata")
def get_huggingface_metadata(options: dict[str, Any]) -> dict[str, Any]:
    repositories = options.get("repositories", [])
    return deps.huggingface_metadata_sizes(repositories if isinstance(repositories, list) else [])


@deps.app.post("/api/llm/huggingface/downloads")
def download_huggingface_model(options: dict[str, Any]) -> dict[str, Any]:
    return deps.start_huggingface_download(str(options.get("repoId", "")), options.get("variant"))


@deps.app.get("/api/llm/huggingface/{organization}/{repository}/gguf-variants")
def get_gguf_variants(organization: str, repository: str) -> dict[str, Any]:
    return deps.gguf_variants(f"{organization}/{repository}")


@deps.app.get("/api/llm/huggingface/downloads/{job_id}")
def get_huggingface_download(job_id: str) -> dict[str, Any]:
    return deps.huggingface_download_status(job_id)


@deps.app.post("/api/llm/huggingface/downloads/{job_id}/cancel")
def cancel_huggingface_download(job_id: str) -> dict[str, Any]:
    return deps.cancel_huggingface_download(job_id)


@deps.app.get("/api/llm/mtp")
def get_mtp_asset() -> dict[str, Any]:
    return deps.mtp_asset_status()


@deps.app.post("/api/llm/mtp/download")
def download_mtp_asset() -> dict[str, Any]:
    return deps.start_mtp_download()


@deps.app.post("/api/llm/mtp/download/{job_id}/cancel")
def cancel_mtp_asset(job_id: str) -> dict[str, Any]:
    return deps.cancel_mtp_download(job_id)


@deps.app.delete("/api/llm/mtp")
def delete_mtp_asset() -> dict[str, Any]:
    return deps.remove_mtp_asset()


@deps.app.post("/api/llm/external/scan")
def scan_external_models(options: dict[str, Any]) -> dict[str, Any]:
    return deps.scan_external_llm_folder(str(options.get("path", "")))


@deps.app.post("/api/llm/external/register")
def register_external_model(options: dict[str, Any]) -> dict[str, Any]:
    return deps.register_external_llm_model(str(options.get("path", "")))

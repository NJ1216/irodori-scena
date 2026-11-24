"""Windows model addition tracks preparation separately from file transfer."""
import sys
import uuid

from server.app_deps import HTTPException
from server.registry import deps
from server.modules.llm_runtime_binding import serialized


def register_download(target, state, variant):
    metadata = {"path": str(target), "repoId": state["repoId"]}
    if WINDOWS_MODEL_ADDITION:
        metadata.update(format="GGUF", variant=variant, backend=deps.selected_backend())
        existing = next((card for card in deps.read_llm_registry()["cards"] if card.get("modelId") == target.name), {})
        previous = existing.get("localMetadata") or {}
        metadata["backend"] = previous.get("backend") or metadata["backend"]
    card = deps.register_local_llm_card(target.name, source="managed", metadata=metadata, prepare=False)
    state["cardId"] = card["id"]
    from server.modules.model_runtime_jobs import start_model_runtime, JOBS, _update
    try:
        start_model_runtime(card["id"], automatic=True)
    except HTTPException as error:
        current = JOBS.get(card["id"], {})
        if current.get("state") not in {"preparing", "waiting-model", "verifying"}:
            state["preparationError"] = str(error.detail)
            failure = {"id": uuid.uuid4().hex, "cardId": card["id"], "runtimeId": card.get("runtimeId"),
                       "previousRuntimeId": card.get("runtimeId"), "automatic": True,
                       "stage": "runtime_preparation", "errorCategory": "runtime_busy"}
            JOBS[card["id"]] = failure
            _update(failure, state="failed", message=str(error.detail))
    state["runtimeJobId"] = JOBS.get(card["id"], {}).get("id")


def download_status(state):
    result = dict(state)
    if not WINDOWS_MODEL_ADDITION:
        return result
    from server.modules.model_runtime_jobs import model_runtime_status
    card = deps.resolve_llm_card(state["cardId"])
    runtime = model_runtime_status({**card, "id": card["cardId"]})
    job = runtime.get("job") or {}
    phase = job.get("state", "interrupted")
    message = state.get("preparationError") or job.get("message", "準備が中断されています。基本動作を確認から再開してください。")
    if state.get("preparationError"):
        phase = "failed"
    if state["state"] in {"failed", "cancelled"}:
        phase, message = state["state"], state.get("error") or "モデル取得を取り消しました。"
        job = {**job, "stage": "model_download", "errorCategory": state.get("errorCategory")}
    elif state.get("cancelRequested"):
        phase, message = "cancelled", "モデル追加を取り消しました。"
    elif phase in {"complete", "failed"} and state["state"] != "complete":
        phase = "waiting-model"
    status = deps.llama_cpp_runtime_status((card.get("localMetadata") or {}).get("backend"))
    progress = status.get("job") or {}
    result["preparation"] = {"state": phase, "stage": job.get("stage"),
                             "errorCategory": job.get("errorCategory"), "message": message,
                             "downloadedBytes": progress.get("downloadedBytes", 0),
                             "totalBytes": progress.get("totalBytes", 0)}
    return result


def cancel_preparation(state):
    if not WINDOWS_MODEL_ADDITION or not state.get("cardId"):
        return
    from server.modules.model_runtime_jobs import cancel_model_runtime
    state["cancelRequested"] = True
    try:
        cancel_model_runtime(state["cardId"])
    except HTTPException as error:
        if error.status_code != 409:
            raise


def pinned_revision(state, fallback):
    if not WINDOWS_MODEL_ADDITION or not state.get("cardId"):
        return fallback
    return (deps.resolve_llm_card(state["cardId"]).get("localMetadata") or {}).get("revision") or fallback


@serialized
def pin_files(state, target, files, revision):
    if not WINDOWS_MODEL_ADDITION or not state.get("cardId"):
        return
    registry = deps.read_llm_registry()
    card = next(item for item in registry["cards"] if item["id"] == state["cardId"])
    card["localMetadata"].update(revision=revision, files=[str(target / item.rfilename) for item in files])
    deps.write_llm_registry(registry)


def addition_active(state):
    if state["state"] not in {"complete", "failed", "cancelled"}:
        return True
    from server.modules.model_runtime_jobs import JOBS
    current = JOBS.get(state.get("cardId"), {})
    return state.get("runtimeJobId") == current.get("id") and state["state"] == "complete" and download_status(state).get("preparation", {}).get("state") in {
        "preparing", "waiting-model", "verifying"}
WINDOWS_MODEL_ADDITION = sys.platform == "win32"

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps
from server.modules.llm_runtime_binding import serialized
from server.modules.llm_probe_response import ProbeResponseError, probe_completion_text, probe_options

MODEL_TESTS: dict[str, dict[str, Any]] = {}
MODEL_TEST_CANCEL: dict[str, threading.Event] = {}
MODEL_TEST_LOCK = threading.RLock()
TERMINAL_STATES = {"passed", "failed", "cancelled"}


def llm_model_test_active(card_id: str | None = None) -> bool:
    with MODEL_TEST_LOCK:
        return any((item["state"] not in TERMINAL_STATES or item.get("localBusy")) and (card_id is None or item["cardId"] == card_id)
                   for item in MODEL_TESTS.values())


def _failure_category(error: BaseException) -> str:
    if isinstance(error, ProbeResponseError):
        return error.category
    message = str(error).lower()
    if isinstance(error, TimeoutError) or "timed out" in message or "timeout" in message:
        return "timeout"
    if isinstance(error, urllib.error.HTTPError) and error.code in {401, 403} or "authentication" in message:
        return "authentication"
    checks = (
        ("disk_full", ("no space left", "disk full", "空き容量", "容量が不足")),
        ("memory_guard", ("memory guard", "memory_guard")),
        ("metal_oom", ("metal", "out of memory", "oom")),
        ("chat_template_missing", ("chat template", "chat_template")),
        ("files_missing", ("no such file", "missing file", "ファイルが見つか")),
        ("architecture_unsupported", ("architecture", "model type", "unsupported model")),
        ("format_unsupported", ("safetensors", "unsupported format", "mlx形式")),
    )
    return next((category for category, needles in checks if any(value in message for value in needles)), "runtime_crash")


def _static_inspection(selected: dict[str, Any]) -> None:
    if selected["source"] not in {"managed", "external"}:
        return
    metadata = selected.get("localMetadata") or {}
    if metadata.get("format") == "GGUF":
        from server.modules.llama_cpp_models import inspect_gguf_files
        inspect_gguf_files(metadata.get("files") or [])
        return
    path = Path(str((selected.get("localMetadata") or {}).get("path", "")))
    if not path.is_dir():
        raise FileNotFoundError("モデルフォルダが見つかりません。")
    if not (path / "config.json").is_file():
        raise FileNotFoundError("config.jsonが見つかりません。")
    if not any(path.glob("*.safetensors")):
        raise ValueError("MLX safetensorsが見つかりません。")


def _local_model_capabilities(selected: dict[str, Any]) -> dict[str, Any]:
    if selected["source"] not in {"managed", "external"}:
        return {}
    metadata = selected.get("localMetadata") or {}
    if metadata.get("format") == "GGUF":
        context = metadata.get("modelContextLimit")
        if isinstance(context, int) and not isinstance(context, bool) and context > 0:
            return {"inputTokenLimit": context, "outputTokenLimit": context,
                    "modelContextLimit": context, "generationMethods": ["chat-completions"],
                    "source": "model-config", "checkedAt": int(time.time() * 1000)}
        return {}
    path = Path(str(metadata.get("path", "")))
    try:
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    text_config = config.get("text_config") if isinstance(config.get("text_config"), dict) else {}
    context = text_config.get("max_position_embeddings") or config.get("max_position_embeddings")
    if isinstance(context, bool) or not isinstance(context, int) or context <= 0:
        return {}
    return {"inputTokenLimit": context, "outputTokenLimit": context,
            "generationMethods": ["chat-completions"], "source": "model-config",
            "checkedAt": int(time.time() * 1000)}


def _completion(selected: dict[str, Any], cancel: threading.Event) -> str:
    if cancel.is_set():
        raise InterruptedError
    request = SimpleNamespace(
        provider=selected["provider"], base_url=selected["baseUrl"], model=selected["model"],
        api_key=selected["apiKey"],
    )
    payload = {"model": selected["model"], "temperature": 0, **probe_options(selected, 64),
               "messages": [{"role": "user", "content": "短く『接続確認済み』と答えてください。"}]}
    if not (selected.get("settings") or {}).get("thinking", False) and "reasoning_effort" not in payload:
        payload["reasoning_effort"] = "none"
    endpoint = request.base_url.rstrip("/")
    endpoint = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
    payload = deps.openai_probe_payload(request, endpoint, payload)
    return probe_completion_text(payload)


def _schema_probe(selected: dict[str, Any], cancel: threading.Event, *, stream: bool) -> dict[str, str | None]:
    if cancel.is_set():
        raise InterruptedError
    schema = {"type": "object", "properties": {"records": {"type": "array", "items": {
        "type": "object", "properties": {"choice": {"type": "string", "enum": ["A"]}},
        "required": ["choice"], "additionalProperties": False,
    }}}, "required": ["records"], "additionalProperties": False}
    payload = {"model": selected["model"], "temperature": 0, **probe_options(selected, 80), "stream": stream,
               "messages": [{"role": "user", "content": "choice Aを1件返してください。"}]}
    thinking = bool((selected.get("settings") or {}).get("thinking", False))
    if selected["provider"] == "ollama":
        payload = {"model": selected["model"], "stream": stream, "think": thinking, "format": schema,
                   "messages": payload["messages"], "options": {"num_predict": 80}}
    else:
        if not thinking and "reasoning_effort" not in payload:
            payload["reasoning_effort"] = "none"
        payload["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "scena_capability_probe", "strict": True, "schema": schema,
        }}
    if selected["provider"] == "lmstudio":
        payload["store"] = False
    endpoint = selected["baseUrl"].rstrip("/")
    if selected["provider"] == "ollama":
        endpoint = f"{endpoint[:-3] if endpoint.endswith('/v1') else endpoint}/api/chat"
    else:
        endpoint = endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
    request = SimpleNamespace(provider=selected["provider"], base_url=selected["baseUrl"],
                              model=selected["model"], api_key=selected["apiKey"])
    try:
        raw, warning = deps.probe_post(request, endpoint, payload)
        if "not enforced" in warning.casefold():
            return {"state": "unsupported", "reasonCode": "response_format_unenforced"}
        if selected["provider"] == "ollama":
            events = [json.loads(line) for line in raw.splitlines() if line.strip()] if stream else [json.loads(raw)]
            content = "".join(str(event.get("message", {}).get("content") or "") for event in events)
        elif stream:
            fragments = []
            for line in raw.splitlines():
                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                    continue
                event = json.loads(line[5:].strip())
                fragments.append(str((event.get("choices") or [{}])[0].get("delta", {}).get("content") or ""))
            content = "".join(fragments)
        else:
            decoded = json.loads(raw)
            content = str(decoded.get("choices", [{}])[0].get("message", {}).get("content") or "")
        result = json.loads(content)
        valid = result == {"records": [{"choice": "A"}]}
        state = "constrained" if selected["provider"] in {"scena-local", "ollama", "lmstudio"} else "schema_validated"
        return {"state": state if valid else "unsupported", "reasonCode": None if valid else "schema_probe_mismatch"}
    except urllib.error.HTTPError as error:
        return {"state": "unsupported", "reasonCode": f"http_{error.code}"}
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return {"state": "unsupported", "reasonCode": "schema_probe_invalid_response"}


def _prepare(selected: dict[str, Any]) -> None:
    if selected["provider"] != "scena-local":
        return
    deps.load_local_llm(selected["model"], settings=selected["settings"])
    selected["baseUrl"] = deps.local_llm_runtime_endpoint()
    selected["apiKey"] = deps.local_llm_runtime_api_key()


def _restore(previous_model: str | None) -> None:
    if previous_model:
        registry = deps.read_llm_registry()
        previous = next((item for item in registry["cards"] if item.get("modelId") == previous_model), None)
        deps.load_local_llm(previous_model, settings=(previous or {}).get("settings") or {})
    else:
        deps.unload_local_llm()


def _run_test(job: dict[str, Any], cancel: threading.Event) -> None:
    job["threadId"] = threading.get_ident()
    card_id = job["cardId"]
    selected = deps.resolve_llm_card(card_id)
    previous_model = deps.local_llm_status().get("model")
    try:
        selected = deps.resolve_llm_card(card_id)
        job["stage"] = "static_inspection"
        _static_inspection(selected)
        capabilities = dict(selected.get("capabilities") or {})
        capabilities.update(_local_model_capabilities(selected))
        if cancel.is_set():
            raise InterruptedError
        job["stage"] = "loading"
        if selected["provider"] == "scena-local":
            deps.shutdown_inference_worker()
        _prepare(selected)
        job["stage"] = "completion"
        try:
            _completion(selected, cancel)
        except (OSError, urllib.error.HTTPError) as first_error:
            if selected["provider"] != "scena-local" or cancel.is_set():
                raise
            deps.stop_local_llm()
            _prepare(selected)
            try:
                _completion(selected, cancel)
            except Exception as retry_error:
                raise retry_error from first_error
        job["stage"] = "schema_nonstream"
        nonstream = _schema_probe(selected, cancel, stream=False)
        job["stage"] = "schema_stream"
        streaming = _schema_probe(selected, cancel, stream=True)
        checked_at = int(time.time() * 1000)
        if selected["provider"] == "scena-local":
            runtime = deps.local_llm_status()
            if runtime.get("contextSize"):
                capabilities.update(runtimeContextLimit=runtime["contextSize"], backend=runtime.get("backend"))
                capabilities["checkedAt"] = checked_at
        capabilities["structuredOutput"] = {
            "nonStreaming": nonstream, "streaming": streaming, "checkedAt": checked_at,
        }
        if selected["provider"] == "scena-local" and selected["settings"].get("mtp"):
            job["stage"] = "engine_verification"
            engine = deps.local_llm_engine_status(selected["model"])
            expected_draft = str(deps.resolve_mtp_draft(selected.get("localMetadata")))
            if (not engine.get("mtpActive") or engine.get("model") != selected["model"]
                    or engine.get("mtpDraftModel") != expected_draft):
                raise RuntimeError("VLM MTP engine fallback detected")
        if cancel.is_set():
            raise InterruptedError
        job.update(state="passed", stage="complete", checkedAt=int(time.time() * 1000),
                   structuredOutput=capabilities["structuredOutput"])
        deps.set_llm_test_status(card_id, {"state": "passed", "checkedAt": job["checkedAt"], "errorCategory": None})
        deps.set_llm_probe(card_id, {
            "state": "passed", "checkedAt": job["checkedAt"], "stages": [
                "authentication", "capabilities", "nonstream", "schema_nonstream", "schema_stream",
            ], "errorCategory": None,
        }, capabilities)
    except InterruptedError:
        job.update(state="cancelled", stage="complete")
        deps.set_llm_test_status(card_id, {"state": "untested", "checkedAt": None, "errorCategory": None})
    except Exception as error:
        category = "invalid_response" if isinstance(error, (LookupError, json.JSONDecodeError)) else _failure_category(error)
        job.update(state="failed", stage="complete", errorCategory=category, error=" ".join(str(error).split())[:500],
                   checkedAt=int(time.time() * 1000))
        deps.set_llm_test_status(card_id, {"state": "failed", "checkedAt": job["checkedAt"], "errorCategory": category})
        deps.set_llm_probe(card_id, {"state": "failed", "checkedAt": job["checkedAt"], "errorCategory": category})
    finally:
        try:
            if selected["provider"] == "scena-local":
                _restore(previous_model)
        except Exception:
            pass
        finally:
            job["localBusy"] = False


@serialized
def start_llm_model_test(card_id: str) -> dict[str, Any]:
    from server.modules.llm_runtime_binding import require_idle
    selected = deps.resolve_llm_card(card_id)
    if selected["provider"] == "scena-local":
        require_idle()
    with MODEL_TEST_LOCK:
        if any(item["state"] not in TERMINAL_STATES for item in MODEL_TESTS.values()):
            raise HTTPException(status_code=409, detail="別のモデルを動作確認中です。")
        job_id = f"llm_test_{uuid.uuid4().hex[:16]}"
        job = {"id": job_id, "cardId": card_id, "state": "queued", "stage": "queued",
               "errorCategory": None, "error": None, "checkedAt": None,
               "localBusy": selected["provider"] == "scena-local"}
        cancel = threading.Event()
        MODEL_TESTS[job_id], MODEL_TEST_CANCEL[job_id] = job, cancel
        deps.set_llm_test_status(card_id, {"state": "testing", "checkedAt": None, "errorCategory": None})
        threading.Thread(target=_run_test, args=(job, cancel), daemon=True).start()
        return dict(job)


def llm_model_test_status(job_id: str) -> dict[str, Any]:
    with MODEL_TEST_LOCK:
        if job_id not in MODEL_TESTS:
            raise HTTPException(status_code=404, detail="モデル動作確認が見つかりません。")
        return dict(MODEL_TESTS[job_id])


def cancel_llm_model_test(job_id: str) -> dict[str, Any]:
    with MODEL_TEST_LOCK:
        if job_id not in MODEL_TEST_CANCEL:
            raise HTTPException(status_code=404, detail="モデル動作確認が見つかりません。")
        MODEL_TEST_CANCEL[job_id].set()
        return dict(MODEL_TESTS[job_id])


deps.register(__name__, ["cancel_llm_model_test", "llm_model_test_active", "llm_model_test_status", "start_llm_model_test"])

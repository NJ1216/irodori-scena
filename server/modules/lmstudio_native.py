from __future__ import annotations

from server.app_deps import Any, Callable, http, json, time, urllib, urlsplit
from server.registry import deps
from server.modules.windows_external_memory import windows_accelerator_handoff


NATIVE_API_REQUIRED = "LM Studio native v1 API が必要です。LM Studio を 0.4 以降へ更新し、native v1 API を有効にしてください。"


def lmstudio_api_root(base_url: str) -> str:
    """Resolve a configured OpenAI-compatible URL to LM Studio's native root."""
    parsed = urlsplit(base_url.rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("LM Studio の接続先は HTTP または HTTPS URL にしてください。")
    return f"{parsed.scheme}://{parsed.netloc}/api/v1"


def _native_error(detail: str = "") -> RuntimeError:
    suffix = f" ({detail[-500:]})" if detail else ""
    return RuntimeError(f"{NATIVE_API_REQUIRED}{suffix}")


def _native_json_request(url: str, *, headers: dict[str, str]) -> dict[str, Any]:
    call = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(call, timeout=10) as response:
            if response.status in {404, 405}:
                raise _native_error()
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code in {404, 405}:
            raise _native_error(detail) from error
        raise RuntimeError(f"LM Studio native v1 API error {error.code}: {detail[-600:]}") from error
    except (OSError, ValueError) as error:
        raise RuntimeError(f"LM Studio native v1 API に接続できません: {error}") from error
    if not isinstance(payload, dict):
        raise _native_error("モデル一覧の応答形式を確認できません。")
    return payload


def _model_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("data", payload.get("models", []))
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _model_name(item: dict[str, Any]) -> str:
    return str(item.get("id") or item.get("key") or item.get("name") or item.get("model") or "").strip()


def _is_llm(item: dict[str, Any]) -> bool:
    model_type = str(item.get("type") or item.get("model_type") or "llm").casefold()
    return model_type in {"llm", "language", "chat", "text"}


def _positive_context(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 4096 else None


def _loaded_context(item: dict[str, Any]) -> int | None:
    instances = item.get("loaded_instances", item.get("loadedInstances", []))
    if not isinstance(instances, list):
        return None
    values = []
    for instance in instances:
        if isinstance(instance, dict):
            config = instance.get("config", {})
            values.append(_positive_context(config.get("context_length")) if isinstance(config, dict) else None)
    return min((value for value in values if value is not None), default=None)


def lmstudio_runtime_details(request: Any) -> tuple[int | None, int | None, str | None]:
    """Read selected-model limits from the native model list without loading it."""
    try:
        payload = _native_json_request(f"{lmstudio_api_root(request.base_url)}/models", headers=deps.request_headers(request.api_key))
        matching = next((item for item in _model_items(payload) if _model_name(item) == request.model and _is_llm(item)), None)
        if matching is None:
            return None, None, f"LM Studio native v1 API で選択モデル「{request.model}」を確認できません。"
        return _positive_context(matching.get("max_context_length")), _loaded_context(matching), None
    except RuntimeError as error:
        return None, None, str(error)


def list_lmstudio_models(request: Any) -> list[str]:
    payload = _native_json_request(f"{lmstudio_api_root(request.base_url)}/models", headers=deps.request_headers(request.api_key))
    return sorted({_model_name(item) for item in _model_items(payload) if _is_llm(item) and _model_name(item)})


def lmstudio_context_length(request: Any, *, system: str = "", user: dict[str, Any] | None = None,
                            max_tokens: int = 0) -> int:
    profile = deps.active_draft_capability_profile()
    if profile is None and user is not None:
        profile = deps.select_call_context(request, system=system, user=user, max_tokens=max_tokens)
    if request.provider == "lmstudio" and isinstance(profile, dict) and isinstance(profile.get("effectiveContext"), int):
        return int(profile["effectiveContext"])
    model_limit, running_limit, error = lmstudio_runtime_details(request)
    if error:
        raise RuntimeError(error)
    requested = deps.target_context_for_memory(deps.local_memory_gib())
    effective = min(requested, model_limit) if model_limit else requested
    return min(effective, running_limit) if running_limit else effective


def _native_payload(request: Any, *, system: str, user: dict[str, Any], max_tokens: int, sampling: dict[str, Any], stream: bool) -> dict[str, Any]:
    payload = {
        "model": request.model,
        "input": json.dumps(user, ensure_ascii=False),
        "system_prompt": system,
        "max_output_tokens": max_tokens,
        "context_length": lmstudio_context_length(request, system=system, user=user, max_tokens=max_tokens),
        "stream": stream,
        "store": False,
    }
    deps.apply_sampling_settings(payload, sampling)
    return payload


def _native_usage(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        return None
    input_tokens = stats.get("input_tokens")
    output_tokens = stats.get("total_output_tokens")
    if all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in (input_tokens, output_tokens)):
        return int(input_tokens) + int(output_tokens)
    return None


def _remember_native_usage(payload: Any) -> int | None:
    total = _native_usage(payload)
    stats = payload.get("stats") if isinstance(payload, dict) else None
    if isinstance(stats, dict) and total is not None:
        deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = {
            "promptTokens": stats["input_tokens"], "completionTokens": stats["total_output_tokens"],
            "totalTokens": total,
        }
    return total


def _native_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise _native_error("チャット応答がJSONオブジェクトではありません。")
    output = payload.get("output")
    candidates = output if isinstance(output, list) else [output]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        message = item.get("message", item)
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
    raise _native_error("チャット応答の output.message.content を確認できません。")


@windows_accelerator_handoff
def lmstudio_json_completion(request: Any, *, system: str, user: dict[str, Any], max_tokens: int,
                             sampling: dict[str, Any], should_cancel: Callable[[], bool] | None = None) -> tuple[str, int | None]:
    body = json.dumps(_native_payload(request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, stream=False), ensure_ascii=False).encode("utf-8")
    connection = None
    try:
        connection, response = deps.openai_http_post(f"{lmstudio_api_root(request.base_url)}/chat", body=body, headers=deps.request_headers(request.api_key), should_cancel=should_cancel)
        response_body = response.read()
        deps._raise_if_draft_cancelled(should_cancel)
        if response.status >= 400:
            detail = response_body.decode("utf-8", errors="replace")
            if response.status in {404, 405}:
                raise _native_error(detail)
            deps.reduce_ollama_context(deps.active_draft_capability_profile(), detail)
            raise RuntimeError(f"LM Studio native v1 API error {response.status}: {detail[-1000:]}")
        payload = json.loads(response_body.decode("utf-8"))
        return _native_content(payload), _remember_native_usage(payload)
    except deps.GenerationCancelled:
        raise
    except (OSError, ValueError, http.client.HTTPException) as error:
        if should_cancel and should_cancel():
            raise deps.GenerationCancelled("台本生成をキャンセルしました。") from error
        raise RuntimeError(f"LM Studio native v1 API に接続できません: {error}") from error
    finally:
        if connection is not None:
            deps.close_openai_http_post(connection)


def _native_stream_event(name: str, event: dict[str, Any]) -> tuple[str, int | None]:
    if name == "error":
        raise _native_error(str(event.get("error") or event.get("message") or ""))
    if name == "chat.end":
        return "", _remember_native_usage(event.get("result"))
    if name != "message.delta":
        return "", None
    delta = event.get("content") or event.get("delta")
    if isinstance(delta, dict):
        delta = delta.get("content")
    return (delta, None) if isinstance(delta, str) else ("", None)


@windows_accelerator_handoff
def lmstudio_stream_text_completion(request: Any, *, system: str, user: dict[str, Any], max_tokens: int,
                                    sampling: dict[str, Any], on_progress: Callable[[str], None] | None,
                                    loop_detector: Callable[[str], str | None] | None,
                                    should_cancel: Callable[[], bool] | None) -> tuple[str, int | None]:
    body = json.dumps(_native_payload(request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, stream=True), ensure_ascii=False).encode("utf-8")
    connection = None
    content = ""
    usage: int | None = None
    event_name = ""
    last_reported_length = 0
    last_reported_at = 0.0
    try:
        connection, response = deps.openai_http_post(f"{lmstudio_api_root(request.base_url)}/chat", body=body, headers=deps.request_headers(request.api_key), should_cancel=should_cancel)
        if response.status >= 400:
            detail = response.read().decode("utf-8", errors="replace")
            if response.status in {404, 405}:
                raise _native_error(detail)
            deps.reduce_ollama_context(deps.active_draft_capability_profile(), detail)
            raise RuntimeError(f"LM Studio native v1 API error {response.status}: {detail[-1000:]}")
        if "text/event-stream" not in str(response.headers.get("content-type", "")).lower():
            payload = json.loads(response.read().decode("utf-8"))
            content = _native_content(payload)
            return content, _remember_native_usage(payload)
        for raw_line in response:
            deps._raise_if_draft_cancelled(should_cancel)
            line = raw_line.decode("utf-8", errors="replace").strip()
            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            delta, event_usage = _native_stream_event(event_name or str(event.get("type") or event.get("event") or ""), event)
            usage = event_usage or usage
            if not delta:
                continue
            content += delta
            now = time.monotonic()
            if on_progress and (len(content) - last_reported_length >= 256 or now - last_reported_at >= 0.25):
                on_progress(content)
                last_reported_length, last_reported_at = len(content), now
            if loop_detector:
                reason = loop_detector(content)
                if reason:
                    raise deps.DraftStreamLoopError(reason, content)
        if not content.strip():
            raise _native_error("ストリーミング応答の message.delta を確認できません。")
        return content, usage
    finally:
        if connection is not None:
            deps.close_openai_http_post(connection)


deps.register(__name__, [
    "NATIVE_API_REQUIRED", "list_lmstudio_models", "lmstudio_context_length", "lmstudio_json_completion",
    "lmstudio_runtime_details", "lmstudio_stream_text_completion", "lmstudio_api_root",
])

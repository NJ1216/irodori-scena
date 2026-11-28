from __future__ import annotations

from typing import Any, Callable, Literal
import sys

from server.app_deps import HTTPException, Path, http, json, urllib
from server.registry import deps
from server.modules.llm_response_reading import (  # noqa: F401 - registered below
    _lmstudio_stream_result,
    _non_stream_response_content,
    _read_text_completion_response,
    _stream_response_content,
    extract_total_tokens,
    extract_usage_metrics,
)
from server.modules.windows_external_memory import windows_accelerator_handoff
from server.modules.anthropic_messages import anthropic_headers, anthropic_models_url, is_anthropic_base_url, model_ids
from server.modules.llm_official_endpoints import chat_model_ids

def request_headers(api_key: str) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key == deps.KEYCHAIN_API_KEY_MARKER:
        api_key = deps.read_connection_api_key()
        if not api_key:
            raise HTTPException(status_code=422, detail="API Key が未設定です。接続ページで設定してください。")
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


def list_llm_models(request: deps.ModelListRequest) -> list[str]:
    if request.provider == "scena-local":
        root = deps.LOCAL_LLM_ROOT / "models"
        managed = [item.name for item in root.iterdir() if item.is_dir()] if root.is_dir() else []
        external = [str(item["id"]) for item in deps.external_local_llm_models() if item["pathAvailable"]]
        return [*managed, *external]
    base = request.base_url.rstrip("/")
    if getattr(request, "provider", "openai") == "ollama":
        root = base[:-3] if base.endswith("/v1") else base
        endpoint = f"{root}/api/tags"
    elif request.provider == "lmstudio":
        return deps.list_lmstudio_models(request)
    elif is_anthropic_base_url(base):
        return _list_anthropic_models(request)
    else:
        endpoint = base if base.endswith("/models") else f"{base}/models"
    call = urllib.request.Request(endpoint, headers=request_headers(request.api_key), method="GET")
    try:
        with urllib.request.urlopen(call, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Model list error {error.code}: {detail[-600:]}") from error
    except OSError as error:
        raise HTTPException(status_code=502, detail=f"Cannot reach the model list endpoint: {error}") from error
    items = payload.get("models", []) if request.provider == "ollama" else payload.get("data", [])
    names = [
        str(item.get("name") or item.get("model") or item.get("id") or "").strip()
        for item in items
        if isinstance(item, dict)
    ]
    return sorted(set(chat_model_ids(base, [name for name in names if name])))


def _fetch_model_page(endpoint: str, headers: dict[str, str]) -> Any:
    call = urllib.request.Request(endpoint, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(call, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=f"Model list error {error.code}: {detail[-600:]}") from error
    except OSError as error:
        raise HTTPException(status_code=502, detail=f"Cannot reach the model list endpoint: {error}") from error


def _list_anthropic_models(request: deps.ModelListRequest) -> list[str]:
    """Anthropic's Models API pages with x-api-key; the bearer header is never sent there."""
    headers = anthropic_headers(request_headers(request.api_key))
    names: list[str] = []
    after: str | None = None
    for _ in range(20):
        ids, after = model_ids(_fetch_model_page(anthropic_models_url(after), headers))
        names.extend(ids)
        if not after:
            break
    return sorted(set(names))

def _lmstudio_json_result(
    request: deps.DraftRequest, *, system: str, user: dict[str, Any], max_tokens: int, temperature: float,
    allow_plain_draft: bool, return_content: bool, debug_response_path: Path | None,
    should_cancel: Callable[[], bool] | None, job_id: str | None, sampling: dict[str, Any],
) -> dict[str, Any] | str:
    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    deps.DRAFT_LLM_THREAD_CONTEXT.last_provider_usage = None
    if debug_response_path is not None:
        deps.write_draft_debug_request(debug_response_path, request=request, system=system, user=user, max_tokens=max_tokens, sampling=sampling)
    profile = deps.active_draft_capability_profile()
    before = profile.get("effectiveContext") if profile else None
    try:
        content, usage = deps.lmstudio_json_completion(request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, should_cancel=should_cancel)
    except RuntimeError:
        if not profile or profile.get("effectiveContext") == before:
            raise
        content, usage = deps.lmstudio_json_completion(request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, should_cancel=should_cancel)
    deps.record_draft_llm_usage(job_id, usage, input_estimate=deps.estimate_llm_input_tokens(system, user),
                                output_text=content, provider=request.provider, model=request.model)
    if debug_response_path is not None:
        deps.write_draft_debug_response(debug_response_path, content)
    if return_content:
        return content
    try:
        return deps.extract_draft_response(content) if allow_plain_draft else deps.extract_json(content)
    except HTTPException as error:
        raise RuntimeError(str(error.detail)) from error


def _completion_options(request: deps.DraftRequest) -> dict[str, Any]:
    """Provider options unrelated to the text protocol itself."""
    options: dict[str, Any] = {}
    if request.provider == "ollama":
        options["reasoning_effort"] = "none"
    elif request.provider == "scena-local":
        settings = deps.resolve_llm_settings(request.provider, request.base_url, request.model)
        if not settings.get("thinking"):
            options["reasoning_effort"] = "none"
    return options


@windows_accelerator_handoff
def openai_json_completion(
    request: deps.DraftRequest,
    *,
    system: str,
    user: dict[str, Any],
    max_tokens: int,
    temperature: float = 0.75,
    allow_plain_draft: bool = False,
    return_content: bool = False,
    debug_response_path: Path | None = None,
    should_cancel: Callable[[], bool] | None = None,
    job_id: str | None = None,
    sampling_policy: Literal["creative", "deterministic"] = "creative",
    feature: str = "llm-json",
    benchmark_seed: int | None = None,
) -> dict[str, Any] | str:
    request = deps.resolve_logical_llm_request(request)
    max_tokens = deps.prepare_draft_llm_call(request, system=system, user=user, max_tokens=max_tokens, feature=feature)
    deps.validate_external_call_context(system=system, user=user, max_tokens=max_tokens)
    sampling = deps.resolve_sampling_settings(request, temperature, sampling_policy)
    logical_request = request
    request = deps.resolve_local_llm_request(request)
    deps.DRAFT_LLM_THREAD_CONTEXT.response_headers = {}
    if request.provider == "lmstudio":
        return _lmstudio_json_result(request, system=system, user=user, max_tokens=max_tokens, temperature=temperature,
                                     allow_plain_draft=allow_plain_draft, return_content=return_content,
                                     debug_response_path=debug_response_path, should_cancel=should_cancel, job_id=job_id, sampling=sampling)
    if deps.ollama_native_enabled(request):
        return deps.ollama_native_json_result(request, system=system, user=user, max_tokens=max_tokens,
            allow_plain_draft=allow_plain_draft, return_content=return_content, debug_response_path=debug_response_path,
            should_cancel=should_cancel, job_id=job_id, sampling=sampling, benchmark_seed=benchmark_seed)
    observation = deps.begin_llm_observation(
        logical_request, feature=feature, system=system, user=user, max_tokens=max_tokens,
    )
    observation["benchmarkSeed"] = benchmark_seed
    base = request.base_url.rstrip("/")
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    if debug_response_path is not None:
        deps.write_draft_debug_request(
            debug_response_path,
            request=logical_request,
            system=system,
            user=user,
            max_tokens=max_tokens,
            sampling=sampling,
        )
    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": max_tokens,
        "stream": False,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": deps.canonical_prompt_json(user)},
        ],
    }
    deps.apply_sampling_settings(payload, sampling)
    if benchmark_seed is not None:
        payload["seed"] = benchmark_seed
    payload.update(_completion_options(logical_request))
    deps.apply_ollama_context(payload, logical_request)
    try:
        response_payload = deps.openai_nonstream_payload(request, endpoint, payload, should_cancel)
    except Exception:
        deps.record_draft_llm_usage(job_id, None, input_estimate=deps.estimate_llm_input_tokens(system, user),
            output_text="", provider=logical_request.provider, model=logical_request.model, failed=True)
        raise
    usage_metrics = extract_usage_metrics(response_payload)
    deps.finish_llm_observation(
        observation, response_path=debug_response_path,
        provider_tokens=extract_total_tokens(response_payload), provider_usage=usage_metrics,
    )
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("The endpoint did not return an OpenAI chat completion.") from error
    deps.record_draft_llm_usage(job_id, usage_metrics, input_estimate=deps.estimate_llm_input_tokens(system, user),
                                output_text=str(content), provider=logical_request.provider, model=logical_request.model)
    if debug_response_path is not None:
        deps.write_draft_debug_response(debug_response_path, content)
    if return_content:
        return str(content)
    try:
        return deps.extract_draft_response(content) if allow_plain_draft else deps.extract_json(content)
    except HTTPException as error:
        raise RuntimeError(str(error.detail)) from error
def openai_text_completion(
    request: deps.DraftRequest, *, system: str,
    user: dict[str, Any],
    max_tokens: int,
    temperature: float = 0.7,
    debug_response_path: Path | None = None,
    should_cancel: Callable[[], bool] | None = None, job_id: str | None = None,
    sampling_policy: Literal["creative", "deterministic"] = "creative",
    feature: str = "llm-text", benchmark_seed: int | None = None,
) -> tuple[str, int | None]:
    result = openai_json_completion(
        request,
        system=system,
        user=user,
        max_tokens=max_tokens,
        temperature=temperature,
        return_content=True,
        debug_response_path=debug_response_path,
        should_cancel=should_cancel,
        job_id=job_id,
        sampling_policy=sampling_policy,
        feature=feature,
        benchmark_seed=benchmark_seed,
    )
    return str(result)


@windows_accelerator_handoff
def openai_stream_text_completion(
    request: deps.DraftRequest,
    *,
    system: str,
    user: dict[str, Any],
    max_tokens: int,
    temperature: float = 0.7,
    debug_response_path: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    loop_detector: Callable[[str], str | None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    job_id: str | None = None,
    sampling_policy: Literal["creative", "deterministic"] = "creative",
    feature: str = "llm-stream",
    benchmark_seed: int | None = None,
    response_format: dict[str, Any] | None = None,
) -> str:
    request = deps.resolve_logical_llm_request(request)
    max_tokens = deps.prepare_draft_llm_call(request, system=system, user=user, max_tokens=max_tokens, feature=feature)
    deps.validate_external_call_context(system=system, user=user, max_tokens=max_tokens)
    sampling = deps.resolve_sampling_settings(request, temperature, sampling_policy)
    logical_request = request
    request = deps.resolve_local_llm_request(request)
    deps.DRAFT_LLM_THREAD_CONTEXT.response_headers = {}
    deps.DRAFT_LLM_THREAD_CONTEXT.finish_reason = None
    deps.DRAFT_LLM_THREAD_CONTEXT.refusal = None
    if request.provider == "lmstudio" and response_format is None:
        return _lmstudio_stream_result(request, system=system, user=user, max_tokens=max_tokens, temperature=temperature,
                                       debug_response_path=debug_response_path, on_progress=on_progress,
                                       loop_detector=loop_detector, should_cancel=should_cancel, job_id=job_id, sampling=sampling)
    if deps.ollama_native_enabled(request) and response_format is None:
        return deps.ollama_native_stream_result(request, system=system, user=user, max_tokens=max_tokens,
            debug_response_path=debug_response_path, on_progress=on_progress, loop_detector=loop_detector,
            should_cancel=should_cancel, job_id=job_id, sampling=sampling, benchmark_seed=benchmark_seed)
    observation = deps.begin_llm_observation(
        logical_request, feature=feature, system=system, user=user, max_tokens=max_tokens,
    )
    observation["benchmarkSeed"] = benchmark_seed
    base = request.base_url.rstrip("/")
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    if debug_response_path is not None:
        deps.write_draft_debug_request(
            debug_response_path,
            request=logical_request,
            system=system,
            user=user,
            max_tokens=max_tokens,
            sampling=sampling,
        )
    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": deps.canonical_prompt_json(user)},
        ],
    }
    if response_format is not None:
        payload["response_format"] = response_format
        if logical_request.provider == "lmstudio":
            payload["store"] = False
    deps.apply_sampling_settings(payload, sampling)
    if benchmark_seed is not None:
        payload["seed"] = benchmark_seed
    payload.update(_completion_options(logical_request))
    deps.apply_ollama_context(payload, logical_request)
    content = ""
    usage: int | None = None
    try:
        content, usage = deps.openai_stream_response(
            request,
            endpoint=endpoint,
            payload=payload,
            debug_response_path=debug_response_path,
            on_progress=on_progress,
            loop_detector=loop_detector,
            should_cancel=should_cancel,
            read_response=_read_text_completion_response,
        )
    except deps.GenerationCancelled:
        deps.write_llm_stream_diagnostic(
            debug_response_path, "request_cancelled", details={"receivedCharacters": len(content)}
        )
        raise
    except (OSError, ValueError, http.client.HTTPException) as error:
        if should_cancel and should_cancel():
            deps.write_llm_stream_diagnostic(
                debug_response_path, "request_cancelled", details={"receivedCharacters": len(content)}
            )
            raise deps.GenerationCancelled("台本生成をキャンセルしました。") from error
        deps.write_llm_stream_diagnostic(
            debug_response_path,
            "request_failed",
            details={"errorType": type(error).__name__, "receivedCharacters": len(content)},
        )
        raise RuntimeError(f"Cannot reach the LLM endpoint: {error}") from error
    except Exception as error:
        deps.write_llm_stream_diagnostic(
            debug_response_path,
            "request_failed",
            details={"errorType": type(error).__name__, "receivedCharacters": len(content)},
        )
        raise
    else:
        deps.write_llm_stream_diagnostic(
            debug_response_path,
            "response_completed",
            details={"receivedCharacters": len(content), "totalTokens": usage},
        )
    finally:
        provider_usage = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None)
        deps.finish_llm_observation(
            observation, response_path=debug_response_path, provider_tokens=usage,
            provider_usage=provider_usage if isinstance(provider_usage, dict) else None,
        )
        deps.DRAFT_LLM_THREAD_CONTEXT.last_provider_usage = provider_usage
        deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
        deps.record_draft_llm_usage(job_id, provider_usage if isinstance(provider_usage, dict) and provider_usage else usage,
                                    input_estimate=deps.estimate_llm_input_tokens(system, user), output_text=content,
                                    provider=logical_request.provider, model=logical_request.model, failed=sys.exc_info()[0] is not None)
        if debug_response_path is not None:
            deps.write_draft_debug_response(debug_response_path, content)
    if on_progress:
        on_progress(content)
    if not content.strip() and not getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "refusal", None):
        raise RuntimeError("The endpoint did not stream any response text.")
    return content

deps.register(
    __name__,
    ["extract_total_tokens", "extract_usage_metrics", "list_llm_models", "openai_json_completion",
     "openai_stream_text_completion", "openai_text_completion", "request_headers"],
)

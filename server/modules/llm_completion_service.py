from __future__ import annotations

import os
import sys
from typing import Any, Callable, Literal

from server.app_deps import Path
from server.registry import deps
from server.modules.llm_retry_budget import reserve_retry


def complete_text(
    request: Any, *, contract: Any, system: str, user: dict[str, Any], max_tokens: int,
    temperature: float = 0.7, debug_response_path: Path | None = None,
    should_cancel: Callable[[], bool] | None = None, job_id: str | None = None,
    sampling_policy: Literal["creative", "deterministic"] = "creative", feature: str | None = None,
    benchmark_seed: int | None = None,
) -> str:
    return deps.openai_text_completion(
        request, system=system, user=user, max_tokens=max_tokens, temperature=temperature,
        debug_response_path=debug_response_path, should_cancel=should_cancel, job_id=job_id,
        sampling_policy=sampling_policy, feature=feature or contract.name,
        benchmark_seed=benchmark_seed,
    )


def complete_stream_text(
    request: Any, *, contract: Any, system: str, user: dict[str, Any], max_tokens: int,
    temperature: float = 0.7, debug_response_path: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    loop_detector: Callable[[str], str | None] | None = None,
    should_cancel: Callable[[], bool] | None = None, job_id: str | None = None,
    sampling_policy: Literal["creative", "deterministic"] = "creative", feature: str | None = None,
    benchmark_seed: int | None = None,
) -> str:
    return deps.openai_stream_text_completion(
        request, system=system, user=user, max_tokens=max_tokens, temperature=temperature,
        debug_response_path=debug_response_path, on_progress=on_progress, loop_detector=loop_detector,
        should_cancel=should_cancel, job_id=job_id, sampling_policy=sampling_policy,
        feature=feature or contract.name, benchmark_seed=benchmark_seed,
    )


def _schema_enabled(request: Any, stream: bool) -> bool:
    if os.getenv("SCENA_DISABLE_STRUCTURED_OUTPUT", "").strip() == "1":
        return False
    if deps.ollama_structured_enabled(request):
        return True
    capabilities = deps.resolve_llm_capabilities(request.provider, request.base_url, request.model)
    structured = capabilities.get("structuredOutput") if isinstance(capabilities, dict) else None
    mode = structured.get("streaming" if stream else "nonStreaming") if isinstance(structured, dict) else None
    return isinstance(mode, dict) and mode.get("state") in {"constrained", "schema_validated"}


def _openai_schema_content(request: Any, contract: Any, *, system: str, user: dict[str, Any],
                           max_tokens: int, temperature: float, sampling_policy: str, should_cancel,
                           benchmark_seed: int | None = None) -> tuple[str, Any]:
    logical = deps.resolve_logical_llm_request(request)
    max_tokens = deps.prepare_draft_llm_call(logical, system=system, user=user,
                                            max_tokens=max_tokens, feature=contract.name)
    resolved = deps.resolve_local_llm_request(logical)
    sampling = deps.resolve_sampling_settings(resolved, temperature, sampling_policy)
    base = resolved.base_url.rstrip("/")
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
    payload = {
        "model": resolved.model, "max_tokens": max_tokens, "stream": False,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": deps.canonical_prompt_json(user)}],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": contract.name.replace("-", "_"), "strict": True, "schema": contract.response_schema,
        }},
    }
    deps.apply_sampling_settings(payload, sampling)
    if benchmark_seed is not None:
        payload["seed"] = benchmark_seed
    if logical.provider == "lmstudio":
        payload["store"] = False
    response = {}
    try:
        response = deps.openai_nonstream_payload(resolved, endpoint, payload, should_cancel)
    finally:
        content = str(((response.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        deps.record_draft_llm_usage(getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None),
            deps.extract_usage_metrics(response) or None,
            input_estimate=deps.estimate_llm_input_tokens(system, user), output_text=content,
            provider=logical.provider, model=logical.model, failed=sys.exc_info()[0] is not None)
    message = response.get("choices", [{}])[0].get("message", {})
    return str(message.get("content") or ""), response


def _structured_content(request: Any, contract: Any, *, system: str, user: dict[str, Any],
                        max_tokens: int, temperature: float, sampling_policy: str, should_cancel,
                        benchmark_seed: int | None = None, debug_response_path=None) -> tuple[str, Any]:
    if request.provider != "ollama":
        return _openai_schema_content(request, contract, system=system, user=user, max_tokens=max_tokens,
                                      temperature=temperature, sampling_policy=sampling_policy,
                                      should_cancel=should_cancel, benchmark_seed=benchmark_seed)
    sampling = deps.resolve_sampling_settings(request, temperature, sampling_policy)
    content = ""
    deps.DRAFT_LLM_THREAD_CONTEXT.provider_usage = None
    try:
        content, _ = deps.ollama_native_completion(
            request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, stream=False,
            should_cancel=should_cancel, format_schema=contract.response_schema,
            benchmark_seed=benchmark_seed, debug_response_path=debug_response_path, feature=contract.name,
        )
    finally:
        deps.record_draft_llm_usage(getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None),
            getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None),
            input_estimate=deps.estimate_llm_input_tokens(system, user), output_text=content,
            provider=request.provider, model=request.model, failed=sys.exc_info()[0] is not None)
    usage = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None)
    finish = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "finish_reason", None)
    usage = usage if isinstance(usage, dict) else {}
    return content, {"choices": [{"message": {"content": content}, "finish_reason": finish}],
                     "usage": {"prompt_tokens": usage.get("promptTokens"),
                               "completion_tokens": usage.get("completionTokens"),
                               "total_tokens": usage.get("totalTokens")}}


def _unsupported_schema(error: BaseException) -> bool:
    if isinstance(error, deps.TransportFailure):
        return error.category == "unsupported_parameter" and not error.partial_body
    message = str(error).casefold()
    return any(value in message for value in ("unsupported", "unknown parameter", "response_format"))


def complete_records(
    request: Any, *, contract: Any, system: str, user: dict[str, Any], max_tokens: int,
    temperature: float = 0.7, stream: bool = False,
    on_records: Callable[[list[dict[str, Any]]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    debug_response_path: Path | None = None,
    sampling_policy: Literal["creative", "deterministic"] = "creative",
    loop_detector: Callable[[str], str | None] | None = None,
    job_id: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    benchmark_seed: int | None = None,
) -> Any:
    schema_mode = _schema_enabled(request, stream)
    mode = "schema" if schema_mode else "legacy"
    if schema_mode and stream:
        try:
            return _stream_records(
                request, contract, system=system, user=user, max_tokens=max_tokens, temperature=temperature,
                on_records=on_records, should_cancel=should_cancel, debug_response_path=debug_response_path,
                sampling_policy=sampling_policy, loop_detector=loop_detector, job_id=job_id,
                benchmark_seed=benchmark_seed, on_progress=on_progress,
            )
        except Exception as error:
            if not _unsupported_schema(error):
                raise
            reserve_retry(error)
            deps.set_structured_output_state(
                request.provider, request.base_url, request.model, stream=True,
                state="unsupported", reason_code="unsupported_parameter",
            )
            return _legacy_records(
                request, contract, system=system, user=user, max_tokens=max_tokens,
                temperature=temperature, should_cancel=should_cancel, on_records=on_records,
                debug_response_path=debug_response_path, sampling_policy=sampling_policy,
                stream=True, loop_detector=loop_detector, job_id=job_id, on_progress=on_progress,
                benchmark_seed=benchmark_seed,
            )
    if schema_mode and not stream:
        if debug_response_path is not None:
            deps.write_draft_debug_request(
                debug_response_path, request=request, system=system,
                user={**user, "outputSchema": contract.response_schema}, max_tokens=max_tokens,
                sampling=deps.resolve_sampling_settings(request, temperature, sampling_policy),
            )
        try:
            content, payload = _structured_content(
                request, contract, system=system, user=user, max_tokens=max_tokens,
                temperature=temperature, sampling_policy=sampling_policy, should_cancel=should_cancel,
                benchmark_seed=benchmark_seed, debug_response_path=debug_response_path,
            )
        except Exception as error:
            if not _unsupported_schema(error):
                raise
            reserve_retry(error)
            deps.set_structured_output_state(
                request.provider, request.base_url, request.model, stream=stream,
                state="unsupported", reason_code="unsupported_parameter",
            )
            schema_mode = False
            mode = "legacy"
        if not schema_mode:
            return _legacy_records(request, contract, system=system, user=user, max_tokens=max_tokens,
                                   temperature=temperature, should_cancel=should_cancel, on_records=on_records,
                                   debug_response_path=debug_response_path, sampling_policy=sampling_policy,
                                   benchmark_seed=benchmark_seed)
        choice = payload.get("choices", [{}])[0]
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        headers = payload.get("_transport_headers", {})
        warning = str(headers.get("warning", "")) if isinstance(headers, dict) else ""
        unenforced = "response_format" in warning.casefold() and "not enforced" in warning.casefold()
        if unenforced:
            deps.set_structured_output_state(
                request.provider, request.base_url, request.model, stream=False,
                state="unsupported", reason_code="response_format_unenforced",
            )
        transport = deps.LlmTransportResult(
            content=content, usage=deps.extract_usage_metrics(payload),
            finish_reason=choice.get("finish_reason") if isinstance(choice, dict) else None,
            refusal=message.get("refusal") if isinstance(message, dict) else None,
            response_headers=headers if isinstance(headers, dict) else {},
            partial=choice.get("finish_reason") in {"length", "missing_terminal_event"} if isinstance(choice, dict) else False,
            warnings=("response_format_unenforced",) if unenforced else (),
        )
        if transport.refusal:
            raw_records, truncated = [], transport.partial
        else:
            raw_records, truncated = deps.extract_contract_records(content, contract)
        if debug_response_path is not None:
            deps.write_draft_debug_response(debug_response_path, content)
        records, manifest = deps.merge_record_fields(raw_records, contract)
        if unenforced and not records and contract.legacy_parser:
            legacy = contract.legacy_parser(content)
            records = legacy if isinstance(legacy, list) else []
        if on_records and records:
            on_records(records)
        return deps.LlmContractResult(tuple(records), mode, content, tuple(manifest),
                                      deps.LlmTransportResult(**{**transport.__dict__, "partial": transport.partial or truncated}))
    return _legacy_records(request, contract, system=system, user=user, max_tokens=max_tokens,
                           temperature=temperature, should_cancel=should_cancel, on_records=on_records,
                           debug_response_path=debug_response_path, sampling_policy=sampling_policy,
                           stream=stream, loop_detector=loop_detector, job_id=job_id, on_progress=on_progress,
                           benchmark_seed=benchmark_seed)


def _legacy_records(request: Any, contract: Any, *, system: str, user: dict[str, Any], max_tokens: int,
                    temperature: float, should_cancel, on_records, debug_response_path: Path | None,
                    sampling_policy: str, stream: bool = False, loop_detector=None, job_id=None,
                    on_progress=None, benchmark_seed: int | None = None) -> Any:
    legacy_system = system + (("\n\n" + contract.legacy_suffix) if contract.legacy_suffix else "")
    complete = complete_stream_text if stream else complete_text
    options = {"on_progress": on_progress, "loop_detector": loop_detector} if stream else {}
    content = complete(request, contract=contract, system=legacy_system, user=user,
                       max_tokens=max_tokens, temperature=temperature, should_cancel=should_cancel,
                       debug_response_path=debug_response_path, sampling_policy=sampling_policy,
                       job_id=job_id, benchmark_seed=benchmark_seed, **options)
    parsed = contract.legacy_parser(content) if contract.legacy_parser else []
    records = parsed if isinstance(parsed, list) else []
    manifest = tuple(
        {"status": "accepted", "owner": record.get(contract.owner_key), "field": key}
        for record in records for key in record if key != contract.owner_key
    )
    if on_records and records:
        on_records(records)
    operator_disabled = os.getenv("SCENA_DISABLE_STRUCTURED_OUTPUT", "").strip() == "1"
    finish = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "finish_reason", None)
    usage = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "last_provider_usage", None)
    transport = deps.LlmTransportResult(
        content=content, warnings=("operator_disabled",) if operator_disabled else (),
        finish_reason=finish, usage=usage if isinstance(usage, dict) else {},
        partial=finish in {"length", "missing_terminal_event"},
    )
    return deps.LlmContractResult(tuple(records), "legacy", content, manifest, transport)


def _stream_records(request: Any, contract: Any, *, system: str, user: dict[str, Any], max_tokens: int,
                    temperature: float, on_records, should_cancel, debug_response_path, sampling_policy,
                    loop_detector, job_id, benchmark_seed, on_progress):
    published = 0
    def progress(content: str) -> None:
        nonlocal published
        if on_progress:
            on_progress(content)
        raw, _ = deps.extract_contract_records(content, contract)
        records, _ = deps.merge_record_fields(raw, contract)
        if on_records and len(records) > published:
            on_records(records[published:])
            published = len(records)
        if loop_detector and contract.loop_projection:
            projected = contract.loop_projection(records)
            reason = loop_detector(projected)
            if reason:
                raise deps.DraftStreamLoopError(reason, projected)
    if request.provider == "ollama":
        sampling = deps.resolve_sampling_settings(request, temperature, sampling_policy)
        content = ""
        try:
            content, _ = deps.ollama_native_completion(
                request, system=system, user=user, max_tokens=max_tokens, sampling=sampling, stream=True,
                on_progress=progress, loop_detector=None, should_cancel=should_cancel, job_id=job_id,
                format_schema=contract.response_schema, benchmark_seed=benchmark_seed,
                debug_response_path=debug_response_path, feature=contract.name,
            )
        finally:
            deps.record_draft_llm_usage(job_id, getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None),
                input_estimate=deps.estimate_llm_input_tokens(system, user), output_text=content,
                provider=request.provider, model=request.model, failed=sys.exc_info()[0] is not None)
    else:
        response_format = {"type": "json_schema", "json_schema": {
            "name": contract.name.replace("-", "_"), "strict": True, "schema": contract.response_schema,
        }}
        content = deps.openai_stream_text_completion(
            request, system=system, user=user, max_tokens=max_tokens, temperature=temperature,
            debug_response_path=debug_response_path, on_progress=progress, should_cancel=should_cancel,
            sampling_policy=sampling_policy, feature=contract.name, response_format=response_format,
            loop_detector=None, job_id=job_id, benchmark_seed=benchmark_seed,
        )
    raw, partial = deps.extract_contract_records(content, contract)
    records, manifest = deps.merge_record_fields(raw, contract)
    headers = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "response_headers", {})
    finish_reason = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "finish_reason", None)
    refusal = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "refusal", None)
    provider_usage = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "provider_usage", None)
    if not isinstance(provider_usage, dict):
        provider_usage = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "last_provider_usage", None)
    warning = str(headers.get("warning", "")) if isinstance(headers, dict) else ""
    unenforced = "response_format" in warning.casefold() and "not enforced" in warning.casefold()
    if unenforced:
        deps.set_structured_output_state(
            request.provider, request.base_url, request.model, stream=True,
            state="unsupported", reason_code="response_format_unenforced",
        )
        if not records and contract.legacy_parser:
            legacy = contract.legacy_parser(content)
            records = legacy if isinstance(legacy, list) else []
    if refusal:
        records = []
    if on_records and len(records) > published:
        on_records(records[published:])
    return deps.LlmContractResult(tuple(records), "schema", content, tuple(manifest),
                                  deps.LlmTransportResult(
                                      content=content,
                                      usage=provider_usage if isinstance(provider_usage, dict) else {},
                                      response_headers=headers if isinstance(headers, dict) else {},
                                      finish_reason=finish_reason, refusal=refusal,
                                      partial=partial or finish_reason in {"length", "missing_terminal_event"},
                                      warnings=("response_format_unenforced",) if unenforced else (),
                                  ))


deps.register(__name__, ["complete_records", "complete_stream_text", "complete_text"])

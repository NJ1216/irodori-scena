from __future__ import annotations

import socket

from server.app_deps import hashlib, http, time, Path, Any, Callable, urlsplit, uuid4
from server.registry import deps
from server.modules.anthropic_messages import MessagesResponse, outgoing_request

# Bound a silent connection, not the total duration of a long script.
LLM_SOCKET_TIMEOUT_SECONDS = 600


class GenerationCancelled(RuntimeError):
    """Raised when a cancellable local inference job is stopped by the user."""


def register_draft_llm_response(response: Any) -> None:
    """Expose this draft thread's in-flight LLM connection to cancellation."""
    job_id = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None)
    if not job_id:
        return
    with deps.DRAFT_LLM_RESPONSES_LOCK:
        deps.DRAFT_LLM_RESPONSES[job_id] = response


def unregister_draft_llm_response(response: Any) -> None:
    job_id = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None)
    if not job_id:
        return
    with deps.DRAFT_LLM_RESPONSES_LOCK:
        if deps.DRAFT_LLM_RESPONSES.get(job_id) is response:
            deps.DRAFT_LLM_RESPONSES.pop(job_id, None)


def close_draft_llm_response(job_id: str) -> None:
    """Close the socket even while connect() or getresponse() is blocking."""
    with deps.DRAFT_LLM_RESPONSES_LOCK:
        response = deps.DRAFT_LLM_RESPONSES.get(job_id)
    # Buffered HTTPResponse.close can wait on the reader's lock. Interrupt recv
    # first, including HTTP/1.0 responses whose connection.sock was detached.
    stream_socket = getattr(response, "sock", None) or getattr(response, "_scena_socket", None)
    if stream_socket is not None:
        try:
            stream_socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass


def _raise_if_draft_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel and should_cancel():
        raise GenerationCancelled("台本生成をキャンセルしました。")


def openai_http_post(
    endpoint: str, *, body: bytes, headers: dict[str, str], should_cancel: Callable[[], bool] | None = None
) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    """Open an OpenAI-compatible response with a cancellable connection.

    The connection is registered before ``request()`` starts, so cancellation
    also interrupts DNS/TCP/TLS setup and the wait for response headers.
    """
    _raise_if_draft_cancelled(should_cancel)
    endpoint, body, headers, anthropic_stream = outgoing_request(endpoint, body, headers)
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("LLM endpoint must be an HTTP or HTTPS URL.")
    path = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    connection_type = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=LLM_SOCKET_TIMEOUT_SECONDS)
    register_draft_llm_response(connection)
    try:
        connection.request("POST", path, body=body, headers=headers)
        connection._scena_socket = getattr(connection, "sock", None)
        response = connection.getresponse()
        _raise_if_draft_cancelled(should_cancel)
        if anthropic_stream is not None:
            response = MessagesResponse(response, stream=anthropic_stream)
        return (connection, response)
    except Exception as error:
        unregister_draft_llm_response(connection)
        try:
            connection.close()
        except OSError:
            pass
        if should_cancel and should_cancel():
            raise GenerationCancelled("台本生成をキャンセルしました。") from error
        raise


def close_openai_http_post(connection: http.client.HTTPConnection) -> None:
    unregister_draft_llm_response(connection)
    close = getattr(connection, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def audio_digest(path: Path) -> str:
    """Return a stable SHA-256 identity for a local reference WAV."""
    digest = hashlib.sha256()
    with path.open("rb") as audio:
        for chunk in iter(lambda: audio.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


deps.register(
    __name__,
    [
        "GenerationCancelled",
        "_raise_if_draft_cancelled",
        "audio_digest",
        "close_draft_llm_response",
        "close_openai_http_post",
        "new_id",
        "now_ms",
        "openai_http_post",
        "register_draft_llm_response",
        "unregister_draft_llm_response",
    ],
)

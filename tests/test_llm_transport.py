from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from server.modules import common, llm_client, llm_transport


class LlmTransportTests(unittest.TestCase):
    def test_done_finishes_without_waiting_for_connection_close(self) -> None:
        def response():
            yield b'data: {"choices":[{"delta":{"content":"usable"}}]}\n'
            yield b'data: [DONE]\n'
            raise AssertionError("Must not read beyond DONE")

        content, _ = llm_client._stream_response_content(
            response(), on_progress=None, loop_detector=None, should_cancel=None)
        self.assertEqual(content, "usable")

    def test_silent_http_connection_has_a_finite_socket_timeout(self) -> None:
        connection = Mock()
        connection.getresponse.side_effect = TimeoutError("silent peer")
        with patch.object(common.http.client, "HTTPConnection", return_value=connection) as factory:
            with self.assertRaises(TimeoutError):
                common.openai_http_post("http://127.0.0.1:9999/v1", body=b"{}", headers={})
        self.assertEqual(factory.call_args.kwargs["timeout"], 600)
        connection.close.assert_called_once()

    def test_stream_timeout_preserves_already_received_text(self) -> None:
        def response():
            yield b'data: {"choices":[{"delta":{"content":"usable"}}]}\n'
            raise TimeoutError("silent peer")

        with self.assertRaises(llm_transport.TransportFailure) as raised:
            llm_client._stream_response_content(response(), on_progress=None, loop_detector=None, should_cancel=None)
        self.assertEqual(raised.exception.partial_body, "usable")
        self.assertFalse(llm_transport.is_retryable(raised.exception, received_body=True))

    def test_retry_policy_stops_after_body_and_never_retries_cancel(self) -> None:
        overloaded = llm_transport.TransportFailure("overloaded", "headers", status=503)
        self.assertTrue(llm_transport.is_retryable(overloaded))
        self.assertFalse(llm_transport.is_retryable(overloaded, received_body=True))
        self.assertFalse(llm_transport.is_retryable(llm_transport.deps.GenerationCancelled("cancel")))

    def test_non_json_success_body_is_an_invalid_response_and_is_not_retried(self) -> None:
        for body in (b"not json", b"[1, 2]", b"\xff\xfe"):
            with self.subTest(body=body):
                response = Mock(status=200, headers={})
                response.read.return_value = body
                request = Mock(provider="openai", api_key="", model="m")
                with (
                    patch("server.modules.common.openai_http_post", return_value=(object(), response)) as post,
                    patch("server.modules.common.close_openai_http_post"),
                    patch.object(llm_transport, "before_attempt"),
                    patch.object(llm_transport, "prepare_gemini_payload", side_effect=lambda _r, p: p),
                ):
                    with self.assertRaises(llm_transport.TransportFailure) as raised:
                        llm_transport.openai_nonstream_payload(request, "http://127.0.0.1:1/v1", {}, None)
                self.assertEqual(raised.exception.category, "invalid_response")
                self.assertEqual(post.call_count, 1)

    def test_retry_after_is_respected_and_backoff_has_jitter(self) -> None:
        self.assertEqual(llm_transport.retry_after_seconds("90"), 90)
        self.assertEqual(llm_transport.retry_after_seconds("2"), 2)
        self.assertEqual(llm_transport.retry_delay(1, random_value=lambda: 0.5), 1.125)
        self.assertEqual(llm_transport.retry_delay(3, random_value=lambda: 0.5), 4.125)

    def test_failure_categories_are_typed_and_secret_free(self) -> None:
        self.assertEqual(llm_transport.classify_http_failure(429, "secret prompt").category, "rate_limit")
        context = llm_transport.classify_http_failure(400, "context token limit exceeded")
        self.assertEqual(context.category, "context_limit")
        self.assertNotIn("secret", str(llm_transport.classify_http_failure(503, "secret")))


if __name__ == "__main__":
    unittest.main()

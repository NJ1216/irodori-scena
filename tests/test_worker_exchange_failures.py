from __future__ import annotations

import scena_test_isolation  # noqa: F401
import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from server.registry import deps
from server import app as _app  # noqa: F401
from server.modules import inference, runtime_state, worker_exchange as exchange


class WorkerExchangeFailureTests(unittest.TestCase):
    def worker(self, data="", *, close_writer=True):
        read_fd, write_fd = os.pipe()
        stdout = os.fdopen(read_fd, "r")
        self.addCleanup(stdout.close)
        os.write(write_fd, data.encode())
        if close_writer:
            os.close(write_fd)
        else:
            self.addCleanup(os.close, write_fd)
        return SimpleNamespace(stdin=io.StringIO(), stdout=stdout), write_fd

    def invoke(self, operation, worker):
        if operation == "prepare":
            return exchange.preparation_response(worker, {"operation": operation})
        return exchange.generation_response(worker, {"operation": operation}, None)

    def test_eof_diagnostics_invalid_json_and_failed_result(self):
        prefix = runtime_state.WORKER_RESULT_PREFIX
        for operation in ("prepare", "synthesize"):
            for data, expected in [
                ("", "stopped unexpectedly"),
                ("diagnostic\n", "diagnostic"),
                (prefix + "{broken\n", "invalid data"),
                (prefix + "[]\n", "invalid data"),
                (prefix + '{"ok":false,"error":"model failed"}\n', "model failed"),
            ]:
                with self.subTest(operation=operation, data=data):
                    worker, _ = self.worker(data)
                    with self.assertRaises((RuntimeError, HTTPException)) as caught:
                        self.invoke(operation, worker)
                    self.assertIn(expected, str(getattr(caught.exception, "detail", caught.exception)))

    def test_timeout_with_no_response_diagnostics_or_result_at_deadline(self):
        prefix = runtime_state.WORKER_RESULT_PREFIX
        for operation in ("prepare", "synthesize"):
            for response in (None, "still loading\n", prefix + '{"ok":true}\n'):
                with self.subTest(operation=operation, response=response):
                    clock = [0.0]
                    reader = Mock()

                    def read(_timeout):
                        clock[0] = 600.0
                        return response

                    reader.read.side_effect = read
                    worker, _ = self.worker(close_writer=False)
                    with patch.object(exchange, "_PipeLines", return_value=reader), patch.object(
                        exchange.time, "monotonic", side_effect=lambda: clock[0],
                    ), self.assertRaises((RuntimeError, HTTPException)) as caught:
                        self.invoke(operation, worker)
                    self.assertIn("timed out", str(getattr(caught.exception, "detail", caught.exception)))
                    reader.close.assert_called_once()

    def test_cancel_closes_reader_without_consuming_another_line(self):
        worker, _ = self.worker(close_writer=False)
        reader = Mock()
        with patch.object(exchange, "_PipeLines", return_value=reader), self.assertRaises(deps.GenerationCancelled):
            exchange.generation_response(worker, {"operation": "synthesize"}, lambda: True)
        reader.read.assert_not_called()
        reader.close.assert_called_once()

    def test_each_exchange_reads_only_its_response_without_background_readers(self):
        worker, writer = self.worker(close_writer=False)
        count = [0]

        def reply():
            count[0] += 1
            result = {"ok": True, "number": count[0]}
            os.write(writer, (runtime_state.WORKER_RESULT_PREFIX + json.dumps(result) + "\n").encode())

        worker.stdin.flush = reply
        with patch("threading.Thread", side_effect=AssertionError("no reader thread")):
            self.assertEqual(self.invoke("prepare", worker)["number"], 1)
            self.assertEqual(self.invoke("synthesize", worker)["number"], 2)
            self.assertEqual(self.invoke("prepare", worker)["number"], 3)

    def test_pipe_reader_preserves_split_utf8_and_partial_eof_line(self):
        worker, writer = self.worker(close_writer=False)
        reader = exchange._PipeLines(worker.stdout)
        self.addCleanup(reader.close)
        encoded = "台詞\n".encode()
        os.write(writer, encoded[:1])
        self.assertIsNone(reader.read(0.1))
        os.write(writer, encoded[1:])
        self.assertEqual(reader.read(0.1), "台詞\n")

    def test_failed_exchange_stops_worker_and_requires_a_fresh_preparation(self):
        worker = Mock()
        worker.poll.return_value = None
        with patch.object(runtime_state, "INFERENCE_WORKER", worker), patch.object(
            inference, "INFERENCE_WORKER_FAILED", False,
        ), patch.object(inference, "preparation_response", side_effect=RuntimeError("timeout")):
            with self.assertRaisesRegex(RuntimeError, "timeout"):
                inference._exchange_response(worker, {"operation": "prepare"})
            self.assertIsNone(runtime_state.INFERENCE_WORKER)
            worker.kill.assert_called_once()
            worker.terminate.assert_not_called()
            worker.stdin.close.assert_not_called()

    def test_non_graceful_stop_kills_without_waiting_for_sigterm(self):
        worker = Mock()
        worker.poll.return_value = None
        # A worker inside a long native call would ignore SIGTERM until the wait expired.
        worker.wait.side_effect = [0]
        with patch.object(runtime_state, "INFERENCE_WORKER", worker):
            inference.stop_inference_worker_locked(graceful=False)
        worker.kill.assert_called_once()
        worker.terminate.assert_not_called()
        worker.stdin.close.assert_not_called()
        worker.wait.assert_called_once_with(timeout=5)

    def test_explicit_stop_closes_stdin_first_and_skips_terminate_when_worker_exits(self):
        worker = Mock()
        worker.poll.side_effect = [None, 0]
        with patch.object(runtime_state, "INFERENCE_WORKER", worker):
            inference.stop_inference_worker_locked()
        worker.stdin.close.assert_called_once()
        worker.wait.assert_called_once_with(timeout=inference.WORKER_GRACEFUL_EXIT_SECONDS)
        worker.terminate.assert_not_called()
        worker.kill.assert_not_called()

    def test_explicit_stop_terminates_when_stdin_close_fails(self):
        worker = Mock()
        worker.poll.return_value = None
        worker.stdin.close.side_effect = BrokenPipeError()
        with patch.object(runtime_state, "INFERENCE_WORKER", worker):
            inference.stop_inference_worker_locked()
        worker.terminate.assert_called_once()

    def test_worker_cleanup_failure_does_not_mask_generation_cancellation(self):
        worker = Mock()
        cancelled = deps.GenerationCancelled("cancelled")
        with (
            patch.object(inference, "generation_response", side_effect=cancelled),
            patch.object(inference, "stop_inference_worker_locked", side_effect=OSError("stop failed")),
            self.assertRaises(deps.GenerationCancelled) as caught,
        ):
            inference._exchange_response(worker, {"operation": "synthesize"}, lambda: True)
        self.assertIs(caught.exception, cancelled)

    def test_diagnostic_retention_matches_the_existing_limit(self):
        worker, _ = self.worker("".join(f"diagnostic {index}\n" for index in range(100)))
        with self.assertRaises(HTTPException) as caught:
            self.invoke("synthesize", worker)
        self.assertEqual(caught.exception.detail, "".join(f"diagnostic {index}\n" for index in range(20, 100)).strip()[-1800:])

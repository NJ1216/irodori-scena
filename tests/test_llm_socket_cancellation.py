from __future__ import annotations

import scena_test_isolation  # noqa: F401
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

import server.app  # noqa: F401
from server.modules import common, runtime_state


class LlmSocketCancellationTests(unittest.TestCase):
    def test_cancel_interrupts_a_silent_response_body_without_waiting_for_peer(self) -> None:
        release_peer = threading.Event()
        reading = threading.Event()
        cancelled = threading.Event()
        finished = threading.Event()
        job_id = "silent_socket_test"

        class SilentPeer(BaseHTTPRequestHandler):
            def do_POST(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.flush()
                release_peer.wait(3)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SilentPeer)
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()

        def read_body():
            runtime_state.DRAFT_LLM_THREAD_CONTEXT.job_id = job_id
            connection = None
            try:
                connection, response = common.openai_http_post(
                    f"http://127.0.0.1:{server.server_port}/chat/completions", body=b"{}", headers={})
                reading.set()
                response.read(1)
            finally:
                if connection is not None:
                    common.close_openai_http_post(connection)
                runtime_state.DRAFT_LLM_THREAD_CONTEXT.job_id = None
                finished.set()

        def cancel():
            common.close_draft_llm_response(job_id)
            cancelled.set()

        worker = threading.Thread(target=read_body, daemon=True)
        cancel_worker = threading.Thread(target=cancel, daemon=True)
        try:
            worker.start()
            self.assertTrue(reading.wait(1))
            cancel_worker.start()
            self.assertTrue(cancelled.wait(1), "Cancellation waited for the silent peer")
            self.assertTrue(finished.wait(1), "Response reader remained blocked after cancellation")
        finally:
            release_peer.set()
            server.shutdown()
            server.server_close()
            worker.join(3)
            if cancel_worker.ident is not None:
                cancel_worker.join(3)
            serving.join(1)


if __name__ == "__main__":
    unittest.main()

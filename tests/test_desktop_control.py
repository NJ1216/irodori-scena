import scena_test_isolation  # noqa: F401
import json
import socket
import threading
import unittest
from unittest.mock import patch

from server.desktop_control import run_desktop


class DesktopControlTests(unittest.TestCase):
    def test_bound_socket_and_parent_disconnect_control_shutdown(self):
        started = threading.Event()
        stopped = threading.Event()
        errors = []

        class Server:
            should_exit = False

            def __init__(self, config):
                pass

            def run(self, sockets):
                self.address = sockets[0].getsockname()
                started.set()
                while not self.should_exit:
                    if stopped.wait(0.01):
                        break

        def run():
            try:
                run_desktop(object())
            except Exception as error:
                errors.append(error)

        with socket.socket() as rendezvous:
            rendezvous.bind(("127.0.0.1", 0))
            rendezvous.listen(1)
            rendezvous.settimeout(2)
            environment = {"SCENA_CONTROL_ADDRESS": f"127.0.0.1:{rendezvous.getsockname()[1]}",
                           "SCENA_DESKTOP": "1", "SCENA_API_TOKEN": "fixture-token"}
            with patch.dict("os.environ", environment), patch("server.desktop_control.uvicorn.Config") as Config, patch(
                "server.desktop_control.uvicorn.Server", Server
            ):
                worker = threading.Thread(target=run)
                worker.start()
                try:
                    control, _ = rendezvous.accept()
                    with control, control.makefile("rb") as stream:
                        message = json.loads(stream.readline())
                        self.assertEqual(message["token"], "fixture-token")
                        self.assertTrue(started.wait(2))
                        with socket.socket() as contender:
                            with self.assertRaises(OSError):
                                contender.bind(("127.0.0.1", message["port"]))
                    worker.join(2)
                    self.assertFalse(worker.is_alive())
                    self.assertEqual(errors, [])
                finally:
                    stopped.set()
                    worker.join(2)
            self.assertFalse(Config.call_args.kwargs["access_log"])
            self.assertIsNone(Config.call_args.kwargs["log_config"])

"""Windows desktop rendezvous: the API keeps its own bound socket throughout."""
import json
import os
import socket
import threading

import uvicorn

from server.uvicorn_options import UVICORN_PROTOCOLS


def run_desktop(app) -> None:
    address = os.environ["SCENA_CONTROL_ADDRESS"]
    host, port = address.rsplit(":", 1)
    if host != "127.0.0.1" or os.environ.get("SCENA_DESKTOP") != "1":
        raise RuntimeError("Invalid desktop control address")
    with socket.socket() as listener, socket.create_connection((host, int(port)), timeout=20) as control:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        control.sendall((json.dumps({"port": listener.getsockname()[1],
                                    "token": os.environ["SCENA_API_TOKEN"]}) + "\n").encode())
        control.settimeout(None)
        # PyInstaller's windowed bootloader intentionally has no stderr. The
        # default Uvicorn formatter probes stderr.isatty(), so desktop release
        # logging must not install that console-dependent configuration.
        server = uvicorn.Server(uvicorn.Config(app, log_level="info", access_log=False, log_config=None,
                                                **UVICORN_PROTOCOLS))

        def watch_control():
            try:
                control.recv(1)
            except OSError:
                pass
            server.should_exit = True

        watcher = threading.Thread(target=watch_control, name="scena-desktop-control", daemon=True)
        watcher.start()
        try:
            server.run(sockets=[listener])
        finally:
            try:
                control.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            watcher.join(timeout=1)

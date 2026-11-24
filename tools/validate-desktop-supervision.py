from __future__ import annotations

import http.client
import os
import signal
import socket
import subprocess
import sys
import time


def child(fd: int) -> None:
    token = "desktop-process-validation-token"
    environment = {**os.environ, "SCENA_DESKTOP": "1", "SCENA_API_TOKEN": token, "SCENA_PARENT_PID": str(os.getpid())}
    process = subprocess.Popen(
        ["uv", "run", "uvicorn", "server.app:app", "--fd", str(fd)],
        pass_fds=(fd,), env=environment,
    )
    os.close(fd)
    print(process.pid, flush=True)
    while True:
        time.sleep(60)


def status(port: int, token: str = "") -> int:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    connection.request("GET", "/api/health", headers=headers)
    response = connection.getresponse()
    response.read()
    connection.close()
    return response.status


def main() -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.set_inheritable(True)
    port = listener.getsockname()[1]
    helper = subprocess.Popen(
        [sys.executable, __file__, "--child", str(listener.fileno())],
        pass_fds=(listener.fileno(),), stdout=subprocess.PIPE, text=True,
    )
    listener.close()
    api_pid = int(helper.stdout.readline().strip())
    deadline = time.monotonic() + 20
    while True:
        try:
            if status(port, "desktop-process-validation-token") == 200:
                break
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError("inherited-FD Uvicorn did not become healthy")
            time.sleep(0.1)
    assert status(port) == 401
    os.kill(helper.pid, signal.SIGKILL)
    helper.wait(timeout=5)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(api_pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.1)
    raise RuntimeError(f"watchdog left Uvicorn PID {api_pid} running")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(int(sys.argv[2]))
    else:
        main()

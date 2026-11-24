"""Deadline-bound, single-owner pipe reads; no reader survives an exchange."""
from __future__ import annotations

import codecs
import json
import os
import selectors
import time
from collections import deque

from fastapi import HTTPException
from server.registry import deps


class _PipeLines:
    def __init__(self, stream):
        self.fd = stream.fileno()
        self.selector = None
        self.windows = None
        if os.name == "nt":
            from server.windows_pipe import WindowsPipe
            self.windows = WindowsPipe(self.fd)
        else:
            self.selector = selectors.DefaultSelector()
            self.selector.register(self.fd, selectors.EVENT_READ)
        self.decoder = codecs.getincrementaldecoder("utf-8")()
        self.buffer = ""
        self.lines = deque()
        self.eof = False

    def read(self, timeout: float) -> str | None:
        if self.lines:
            return self.lines.popleft()
        if self.eof:
            return ""
        if self.windows is not None:
            chunk = self.windows.read(timeout)
            if chunk is None:
                return None
        else:
            if not self.selector.select(timeout):
                return None
            chunk = os.read(self.fd, 65536)
        self.buffer += self.decoder.decode(chunk, final=not chunk)
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            self.lines.append(line + "\n")
        if not chunk:
            self.eof = True
            if self.buffer:
                self.lines.append(self.buffer)
                self.buffer = ""
        return self.lines.popleft() if self.lines else "" if self.eof else None

    def close(self):
        if self.selector is not None:
            self.selector.close()


def _check_wait(deadline, operation, should_cancel):
    if should_cancel and should_cancel():
        raise deps.GenerationCancelled("エクスポートをキャンセルしました。")
    if time.monotonic() >= deadline:
        raise HTTPException(status_code=504, detail=f"Irodori-TTS {operation} timed out.")


def _read_response(reader, deadline, operation, should_cancel):
    diagnostics = deque(maxlen=80)
    while True:
        _check_wait(deadline, operation, should_cancel)
        line = reader.read(min(0.1, max(0, deadline - time.monotonic())))
        # An arrival at the deadline must not turn a timeout into success.
        _check_wait(deadline, operation, should_cancel)
        if line is None:
            continue
        if not line:
            detail = "".join(diagnostics).strip() or "Irodori-TTS worker stopped unexpectedly."
            raise HTTPException(status_code=500, detail=detail[-1800:])
        if not line.startswith(deps.WORKER_RESULT_PREFIX):
            diagnostics.append(line)
            continue
        try:
            response = json.loads(line.removeprefix(deps.WORKER_RESULT_PREFIX))
            if not isinstance(response, dict):
                raise ValueError("response must be an object")
        except ValueError as error:
            raise HTTPException(status_code=500, detail="Irodori-TTS worker returned invalid data.") from error
        if not response.get("ok"):
            raise HTTPException(status_code=500, detail=str(response.get("error") or f"Irodori-TTS {operation} failed.")[-1800:])
        return response


def _exchange(worker, request, should_cancel=None):
    if worker.stdin is None or worker.stdout is None:
        raise HTTPException(status_code=500, detail="Irodori-TTS worker streams are unavailable.")
    operation = "preparation" if request["operation"] == "prepare" else "generation"
    deadline = time.monotonic() + 600
    reader = _PipeLines(worker.stdout)
    try:
        worker.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        worker.stdin.flush()
        return _read_response(reader, deadline, operation, should_cancel)
    except (OSError, UnicodeError) as error:
        raise HTTPException(status_code=500, detail="Irodori-TTS worker stopped unexpectedly.") from error
    finally:
        reader.close()


def generation_response(worker, request, should_cancel):
    return _exchange(worker, request, should_cancel)


def preparation_response(worker, request):
    try:
        return _exchange(worker, request)
    except HTTPException as error:
        raise RuntimeError(error.detail) from error

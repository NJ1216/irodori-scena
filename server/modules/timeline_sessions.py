"""Reject late playback requests after stop, restart, or workspace replacement."""

from __future__ import annotations

import threading
from fastapi import HTTPException

_LOCK = threading.Lock()
_CLIENTS: dict[str, tuple[int, str, str, bool]] = {}


def accept(client: str, sequence: int, playback: str, workspace: str) -> None:
    with _LOCK:
        previous = _CLIENTS.get(client)
        if previous is not None:
            old_sequence, old_playback, old_workspace, stopped = previous
            if sequence < old_sequence or (
                sequence == old_sequence and (old_playback != playback or old_workspace != workspace or stopped)
            ):
                raise HTTPException(409, "Playback session is stale.")
        _CLIENTS[client] = (sequence, playback, workspace, False)


def stop(client: str, sequence: int, playback: str) -> None:
    with _LOCK:
        previous = _CLIENTS.get(client)
        if previous and previous[0] > sequence:
            return
        workspace = previous[2] if previous else ""
        _CLIENTS[client] = (sequence, playback, workspace, True)

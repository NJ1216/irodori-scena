from __future__ import annotations

from collections import deque
import threading
import time
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps

TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "cancelled"}
JOB_TTL_MS = 60 * 60 * 1000
JOB_LIMIT = 100
PROPOSAL_LIMIT = 50
TOMBSTONE_LIMIT = 1000

_expired_order: deque[str] = deque()
_expired_ids: set[str] = set()
_lock = threading.RLock()


def _timestamp(item: dict[str, Any]) -> int:
    return int(item.get("completedAt") or item.get("createdAt") or item.get("startedAt") or 0)


def _remember_expired(identifier: str) -> None:
    with _lock:
        if identifier in _expired_ids:
            return
        _expired_ids.add(identifier)
        _expired_order.append(identifier)
        while len(_expired_order) > TOMBSTONE_LIMIT:
            _expired_ids.discard(_expired_order.popleft())


def is_expired(identifier: str) -> bool:
    with _lock:
        return identifier in _expired_ids


def raise_missing(identifier: str, detail: str) -> None:
    if is_expired(identifier):
        raise HTTPException(status_code=410, detail="Job or proposal expired.")
    raise HTTPException(status_code=404, detail=detail)


def evict_terminal_jobs(
    jobs: dict[str, dict[str, Any]], lock: threading.RLock, *, now_ms: int | None = None,
) -> list[str]:
    now = int(time.time() * 1000) if now_ms is None else now_ms
    with lock:
        terminal = [(identifier, item) for identifier, item in jobs.items()
                    if item.get("status") in TERMINAL_STATUSES]
        expired = {identifier for identifier, item in terminal
                   if _timestamp(item) and now - _timestamp(item) >= JOB_TTL_MS}
        newest = sorted(terminal, key=lambda pair: _timestamp(pair[1]), reverse=True)
        expired.update(identifier for identifier, _item in newest[JOB_LIMIT:])
        for identifier in expired:
            jobs.pop(identifier, None)
    for identifier in expired:
        deps.PROGRESS_EVENTS.discard(identifier)
        _remember_expired(identifier)
    return sorted(expired)


def evict_script_assistant_proposals(*, now_ms: int | None = None) -> list[str]:
    now = int(time.time() * 1000) if now_ms is None else now_ms
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        proposals = list(deps.SCRIPT_ASSISTANT_PROPOSALS.items())
        expired = {identifier for identifier, item in proposals
                   if _timestamp(item) and now - _timestamp(item) >= JOB_TTL_MS}
        newest = sorted(proposals, key=lambda pair: _timestamp(pair[1]), reverse=True)
        expired.update(identifier for identifier, _item in newest[PROPOSAL_LIMIT:])
        for identifier in expired:
            deps.SCRIPT_ASSISTANT_PROPOSALS.pop(identifier, None)
    for identifier in expired:
        _remember_expired(identifier)
    return sorted(expired)


def reset_expired_tombstones() -> None:
    with _lock:
        _expired_order.clear()
        _expired_ids.clear()


deps.register(__name__, ["evict_script_assistant_proposals", "evict_terminal_jobs", "is_expired",
                         "raise_missing", "reset_expired_tombstones"])

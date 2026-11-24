from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import threading
import time
from typing import Any, Iterator

from server.registry import deps
from server.modules.job_publication import PublicJob

TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed", "cancelled"}


@dataclass(frozen=True)
class ProgressEvent:
    sequence: int
    job_id: str
    phase: str
    current: float
    total: float
    timestamp: str
    terminal: bool
    body: str

    @property
    def metrics(self) -> dict[str, Any]:
        return self.public()["metrics"]

    def public(self) -> dict[str, Any]:
        return json.loads(self.body)



class ProgressEventStore:
    """Bounded, process-local replay buffer for job progress streams."""

    def __init__(self, max_events: int = 256, *, max_bytes: int = 2 * 1024 * 1024) -> None:
        self._max_events = max(1, max_events)
        self._max_bytes = max(1, max_bytes)
        self._events: dict[str, deque[tuple[ProgressEvent, int]]] = {}
        self._bytes: dict[str, int] = {}
        self._fingerprints: dict[str, bytes] = {}
        self._sequences: dict[str, int] = {}
        self._versions: dict[str, int] = {}
        self._condition = threading.Condition()

    def observe(self, job: dict[str, Any]) -> ProgressEvent | None:
        job_id = str(job.get("id", ""))
        if not job_id:
            raise ValueError("progress events require a job id")
        fingerprint = hashlib.sha256(json.dumps(job, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).digest()
        with self._condition:
            version = job.version if isinstance(job, PublicJob) else None
            if version is not None:
                if version <= self._versions.get(job_id, 0):
                    return None
                self._versions[job_id] = version
            elif job_id in self._versions:
                return None
            if self._fingerprints.get(job_id) == fingerprint:
                return None
            sequence = self._sequences.get(job_id, 0) + 1
            event = _from_job(job, sequence)
            self._fingerprints[job_id] = fingerprint
            self._sequences[job_id] = sequence
            events = self._events.setdefault(job_id, deque())
            size = len(event.body.encode("utf-8"))
            events.append((event, size))
            retained_bytes = self._bytes.get(job_id, 0) + size
            # Keep the latest complete snapshot even when it alone exceeds the budget.
            # Eviction preserves sequence numbers so consumers can reconcile gaps.
            while len(events) > 1 and (len(events) > self._max_events or retained_bytes > self._max_bytes):
                retained_bytes -= events.popleft()[1]
            self._bytes[job_id] = retained_bytes
            self._condition.notify_all()
            return event

    def after(self, job_id: str, sequence: int) -> list[ProgressEvent]:
        with self._condition:
            return [event for event, _ in self._events.get(job_id, ()) if event.sequence > sequence]

    def wait_after(self, job_id: str, sequence: int, timeout: float) -> list[ProgressEvent]:
        with self._condition:
            events = [event for event, _ in self._events.get(job_id, ()) if event.sequence > sequence]
            if events:
                return events
            self._condition.wait(timeout=max(0.0, timeout))
            return [event for event, _ in self._events.get(job_id, ()) if event.sequence > sequence]

    def discard(self, job_id: str) -> None:
        with self._condition:
            self._events.pop(job_id, None)
            self._bytes.pop(job_id, None)
            self._fingerprints.pop(job_id, None)
            self._sequences.pop(job_id, None)
            self._versions.pop(job_id, None)


def _from_job(job: dict[str, Any], sequence: int) -> ProgressEvent:
    status = str(job.get("status", "unknown"))
    phase = str(job.get("phase") or status)
    current, total = _progress_pair(job)
    excluded = {"id", "phase", "status", "request", "characters", "plan", "continuity"}
    metrics = {key: value for key, value in job.items() if key not in excluded}
    metrics["status"] = status
    timestamp = datetime.now(UTC).isoformat()
    terminal = status in TERMINAL_STATUSES
    body = json.dumps({"sequence": sequence, "jobId": str(job["id"]), "phase": phase,
                       "current": current, "total": total, "metrics": metrics,
                       "timestamp": timestamp, "terminal": terminal}, ensure_ascii=False, separators=(",", ":"))
    return ProgressEvent(sequence, str(job["id"]), phase, current, total, timestamp, terminal, body)


def _progress_pair(job: dict[str, Any]) -> tuple[float, float]:
    if "overallProgress" in job:
        return float(job.get("overallProgress", 0.0)), 100.0
    if job.get("status") == "aligning" or job.get("phase") == "aligning":
        return float(job.get("alignmentCompletedLines", 0)), float(job.get("alignmentTotalLines", 0))
    for current_key, total_key in (("completedLines", "totalLines"),
                                   ("performanceCompletedLines", "performanceTotalLines"),
                                   ("completedChunks", "totalChunks")):
        if current_key in job and total_key in job:
            return float(job.get(current_key, 0)), float(job.get(total_key, 0))
    return 0.0, 0.0


def format_sse(event: ProgressEvent) -> str:
    return f"id: {event.sequence}\nevent: progress\ndata: {event.body}\n\n"


PROGRESS_EVENTS = ProgressEventStore()


def stream_progress(snapshot: Callable[[str], dict[str, Any]], job_id: str,
                    last_sequence: int = 0) -> Iterator[str]:
    sequence = max(0, last_sequence)
    last_heartbeat = time.monotonic()
    PROGRESS_EVENTS.observe(snapshot(job_id))
    while True:
        events = PROGRESS_EVENTS.after(job_id, sequence)
        if not events:
            events = PROGRESS_EVENTS.wait_after(job_id, sequence, 15.0)
        if not events:
            # Reconcile missed publications and expired jobs at heartbeat cadence.
            PROGRESS_EVENTS.observe(snapshot(job_id))
            events = PROGRESS_EVENTS.after(job_id, sequence)
        if not events:
            if time.monotonic() - last_heartbeat >= 15:
                yield ": keep-alive\n\n"
                last_heartbeat = time.monotonic()
            continue
        for event in events:
            sequence = event.sequence
            yield format_sse(event)
            if event.terminal:
                return


deps.register(__name__, ["PROGRESS_EVENTS", "ProgressEvent", "ProgressEventStore", "format_sse", "stream_progress"])

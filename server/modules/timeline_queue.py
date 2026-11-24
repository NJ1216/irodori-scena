"""One cancellable interval worker; playback promotes current work in place."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from server.modules.timeline_intervals import render_interval, background_intervals, describe_interval


@dataclass
class Work:
    interval: dict[str, Any]
    priority: int
    sequence: int
    cancel: threading.Event = field(default_factory=threading.Event)


class IntervalQueue:
    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.work: dict[str, Work] = {}
        self.active: Work | None = None
        self.thread: threading.Thread | None = None
        self.sequence = 0
        self.background = iter(())
        self.background_plan_id = None

    def reset(self) -> None:
        with self.condition:
            if self.active:
                self.active.cancel.set()
            self.work.clear()
            self.background = iter(())
            self.background_plan_id = None
            self.condition.notify_all()

    def background_plan(self, plan: dict[str, Any]) -> None:
        with self.condition:
            if self.background_plan_id == plan["planId"]:
                return
            self.background_plan_id = plan["planId"]
            self.background = background_intervals(plan)
            for key, work in list(self.work.items()):
                if work.interval["status"] == "ready":
                    continue
                old = work.interval
                targets = set(old["targets"]) if old.get("targets") is not None else None
                replacement = describe_interval(plan, old["startFrame"], old["endFrame"], targets)
                if replacement["intervalId"] == key:
                    continue
                if work is self.active:
                    work.cancel.set()
                self.work.pop(key, None)
            self._ensure_worker()
            self.condition.notify_all()

    def _ensure_worker(self) -> None:
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, daemon=True, name="scena-timeline")
            self.thread.start()

    def _next_background(self) -> Work | None:
        for interval in self.background:
            if interval["status"] != "queued":
                continue
            key = interval["intervalId"]
            if key in self.work:
                continue
            self.sequence += 1
            work = Work(interval, 10, self.sequence)
            self.work[key] = work
            return work
        return None

    def submit(self, intervals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self.condition:
            wanted = {item["intervalId"] for item in intervals}
            if wanted and self.active and self.active.interval["intervalId"] not in wanted:
                self.active.cancel.set()
            for work in self.work.values():
                work.priority = 10
            result = []
            for rank, interval in enumerate(intervals):
                key = interval["intervalId"]
                if interval["status"] in {"silence", "waiting-input", "ready"}:
                    result.append(interval)
                    continue
                work = self.work.get(key)
                if work is None or work.interval["status"] == "stale":
                    self.sequence += 1
                    work = Work(interval, rank, self.sequence)
                    self.work[key] = work
                work.priority = rank
                state = {key: value for key, value in work.interval.items() if key in {"status", "audioUrl", "error", "startedAt"}}
                result.append({**interval, **state})
            # Completed metadata is expendable; immutable WAVs remain reusable.
            if len(self.work) > 512:
                self.work = {
                    key: work
                    for key, work in self.work.items()
                    if key in wanted or work is self.active or work.interval["status"] in {"queued", "rendering"}
                }
            self._ensure_worker()
            self.condition.notify_all()
            return result

    def _run(self) -> None:
        while True:
            with self.condition:
                pending = [work for work in self.work.values() if work.interval["status"] == "queued"]
                if not pending:
                    background = self._next_background()
                    if background is None:
                        self.condition.wait()
                        continue
                    pending = [background]
                work = min(pending, key=lambda item: (item.priority, item.sequence))
                self.active = work
                work.cancel.clear()
                work.interval = {**work.interval, "status": "rendering", "startedAt": time.time()}
            try:
                result = render_interval(work.interval, work.cancel.is_set)
            except InterruptedError:
                result = {**work.interval, "status": "queued"}
            except Exception as error:
                result = {**work.interval, "status": "failed", "error": str(error)}
            with self.condition:
                work.interval = result
                self.active = None
                self.condition.notify_all()


QUEUE = IntervalQueue()

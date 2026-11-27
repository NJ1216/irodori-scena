"""Blob protection for history snapshots captured by requests still in flight."""

from __future__ import annotations

from typing import Any


class PendingCaptures:
    """Reference counts of blob digests held by captured, unfinished snapshots.

    A concurrent commit prunes blobs that no history entry references; digests
    counted here are skipped so the in-flight request can still commit them.
    Callers hold the history lock. reset() starts a new generation so a release
    arriving after a session change cannot alter the new session's counts.
    """

    def __init__(self) -> None:
        self.blobs: dict[str, int] = {}
        self._owners: dict[int, int] = {}
        self._generation = 0

    def hold(self, snapshot: dict[str, Any]) -> None:
        for digest in snapshot["files"].values():
            self.blobs[digest] = self.blobs.get(digest, 0) + 1
        self._owners[id(snapshot)] = self._generation

    def release(self, snapshot: dict[str, Any]) -> None:
        if self._owners.pop(id(snapshot), None) != self._generation:
            return
        for digest in snapshot["files"].values():
            remaining = self.blobs.get(digest, 0) - 1
            if remaining > 0:
                self.blobs[digest] = remaining
            else:
                self.blobs.pop(digest, None)

    def reset(self) -> None:
        self.blobs.clear()
        self._owners.clear()
        self._generation += 1

"""Injectable per-line preparation, independent of external wire/FCP/selection.

No adapters are registered. Lifetime and deduplication are limited to one service
instance. Failed/cancelled operations are sticky; no automatic retry or deletion.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
import threading
from typing import Callable

from server.modules.motion_preparation_artifacts import (
    PreparationRequest, PreparationSnapshot, PreparedBundle, ProposedAudio, ProposedLab,
    assemble_bundle, wav_details,
)


class PreparationCancelled(Exception):
    pass


class PreparationSourceChanged(Exception):
    pass


class PreparationStopped(Exception):
    """A prior failed/cancelled request must be reconciled, not automatically retried."""


@dataclass(frozen=True)
class PreparationDependencies:
    capture: Callable[[PreparationRequest], PreparationSnapshot]
    load_audio: Callable[[PreparationSnapshot, Callable[[], None]], ProposedAudio]
    generate_audio: Callable[[PreparationSnapshot, Callable[[], None]], ProposedAudio]
    derive_lab: Callable[[ProposedAudio, Callable[[], None]], ProposedLab]
    stage_bundle: Callable[[PreparedBundle, Callable[[], None]], str]
    verify_staging: Callable[[PreparationRequest, PreparedBundle, str, Callable[[], None]], None]


@dataclass
class PreparationAttempt:
    request: PreparationRequest
    state: str = "pending"
    snapshot: PreparationSnapshot | None = None
    audio: ProposedAudio | None = None
    bundle: PreparedBundle | None = None
    staging_started: bool = False
    staging_receipt: str | None = None


class MotionPreparationService:
    def __init__(self, dependencies: PreparationDependencies, *, max_operations: int = 64):
        if max_operations <= 0:
            raise ValueError("Preparation operation capacity must be positive.")
        self.dependencies = dependencies
        self.max_operations = max_operations
        self._guard = threading.Lock()
        self._entries: dict[str, tuple[PreparationAttempt, threading.Lock]] = {}

    def inspect(self, operation_id: str) -> PreparationAttempt | None:
        """Detached recovery evidence; audio/staging never implies FCP adoption."""
        with self._guard:
            entry = self._entries.get(operation_id)
        if entry:
            with entry[1]:
                return deepcopy(entry[0])
        return None

    def _entry(self, request: PreparationRequest):
        with self._guard:
            if request.operation_id not in self._entries:
                if len(self._entries) >= self.max_operations:
                    raise PreparationStopped("Preparation instance is full; reconcile retained operations.")
                self._entries[request.operation_id] = (PreparationAttempt(request), threading.RLock())
            attempt, lock = self._entries[request.operation_id]
            if attempt.request != request:
                raise ValueError("Preparation operation identity belongs to another source.")
            return attempt, lock

    def _capture(self, request: PreparationRequest) -> PreparationSnapshot:
        snapshot = deepcopy(self.dependencies.capture(request))
        source = snapshot.source
        if (source.project_id, source.scene_id, source.line_id) != (request.project_id, request.scene_id, request.line_id):
            raise PreparationSourceChanged("Preparation source identity differs from the request.")
        if not isinstance(snapshot.inputs_identity, str) or not snapshot.inputs_identity.strip():
            raise ValueError("Preparation requires a relevant-inputs identity.")
        return snapshot

    def _assert_current(self, request: PreparationRequest, before: PreparationSnapshot) -> None:
        after = self._capture(request)
        # Revision is independent of content; own/unrelated revision increments do
        # not by themselves invalidate this read-only preparation.
        if (replace(after.source, project_revision=0) != replace(before.source, project_revision=0)
                or after.inputs_identity != before.inputs_identity):
            raise PreparationSourceChanged("Preparation source inputs changed.")

    def prepare(self, request: PreparationRequest, should_cancel: Callable[[], bool]) -> PreparationAttempt:
        def checkpoint():
            if should_cancel():
                raise PreparationCancelled("Preparation was cancelled.")

        checkpoint()
        attempt, lock = self._entry(request)
        while not lock.acquire(timeout=0.05):
            checkpoint()
        try:
            checkpoint()
            if attempt.state == "prepared":
                return self._replay(attempt, checkpoint)
            if attempt.state != "pending":
                raise PreparationStopped(f"Preparation already ended with {attempt.state}; reconcile before retry.")
            return self._prepare_once(attempt, checkpoint)
        finally:
            lock.release()

    def _replay(self, attempt: PreparationAttempt, checkpoint: Callable[[], None]) -> PreparationAttempt:
        try:
            self._assert_current(attempt.request, attempt.snapshot)
            self._verify_selected_audio(attempt, checkpoint)
            self._verify_staging(attempt, checkpoint)
            self._assert_current(attempt.request, attempt.snapshot)
            checkpoint()
            return deepcopy(attempt)
        except PreparationCancelled:
            attempt.state = "cancelled"
            raise
        except Exception:
            attempt.state = "failed"
            raise

    def _prepare_once(self, attempt: PreparationAttempt, checkpoint: Callable[[], None]) -> PreparationAttempt:
        try:
            attempt.snapshot = self._capture(attempt.request)
            checkpoint()
            snapshot = attempt.snapshot
            if snapshot.source.gap_seconds is None:
                raise ValueError("Preparation interval is unspecified.")
            attempt.state = "audio"
            producer = self.dependencies.generate_audio if snapshot.source.needs_generation else self.dependencies.load_audio
            attempt.audio = deepcopy(producer(deepcopy(snapshot), checkpoint))
            checkpoint()
            wav_details(attempt.audio.wav)
            self._assert_current(attempt.request, snapshot)
            attempt.state = "lab"
            lab = self.dependencies.derive_lab(attempt.audio, checkpoint)
            checkpoint()
            attempt.bundle = assemble_bundle(snapshot, attempt.audio, deepcopy(lab))
            self._assert_current(attempt.request, snapshot)
            self._verify_selected_audio(attempt, checkpoint)
            self._assert_current(attempt.request, snapshot)
            checkpoint()
            attempt.state = "staging"
            attempt.staging_started = True
            attempt.staging_receipt = self.dependencies.stage_bundle(deepcopy(attempt.bundle), checkpoint)
            checkpoint()
            if not isinstance(attempt.staging_receipt, str) or not attempt.staging_receipt.strip():
                raise ValueError("Preparation staging returned no receipt.")
            self._assert_current(attempt.request, snapshot)
            self._verify_selected_audio(attempt, checkpoint)
            self._assert_current(attempt.request, snapshot)
            checkpoint()
            self._verify_staging(attempt, checkpoint)
            self._assert_current(attempt.request, snapshot)
            checkpoint()
            attempt.state = "prepared"
            return deepcopy(attempt)
        except PreparationCancelled:
            attempt.state = "cancelled"
            raise
        except Exception:
            attempt.state = "failed"
            raise

    def _verify_selected_audio(self, attempt: PreparationAttempt, checkpoint: Callable[[], None]) -> None:
        if attempt.snapshot.source.needs_generation:
            return
        current = self.dependencies.load_audio(deepcopy(attempt.snapshot), checkpoint)
        if current.take_id != attempt.audio.take_id or wav_details(current.wav)[2] != attempt.bundle.wav_sha256:
            raise PreparationSourceChanged("Selected WAV content changed during preparation.")

    def _verify_staging(self, attempt: PreparationAttempt, checkpoint: Callable[[], None]) -> None:
        self.dependencies.verify_staging(
            attempt.request, deepcopy(attempt.bundle), attempt.staging_receipt, checkpoint,
        )
        checkpoint()
        self._verify_selected_audio(attempt, checkpoint)

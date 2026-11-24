"""POSIX local fixture staging; three media files, process-local receipts only.

All mutations use directory descriptors below an explicitly opened existing root.
Publication uses exclusive directory creation and non-overwriting hard links.
No public manifest, adoption, durable deduplication or selection is implemented.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import threading
from typing import Callable
from uuid import uuid4

from server.modules.motion_preparation import PreparationCancelled, PreparationStopped
from server.modules.motion_preparation_artifacts import PreparationRequest, PreparedBundle, assemble_bundle

_FILES = ("dialogue.wav", "dialogue.txt", "dialogue.lab")
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


@dataclass(frozen=True)
class LocalStageReceipt:
    request: PreparationRequest
    token: str
    directory: str
    content_version: str
    digests: tuple[str, str, str]
    directory_identity: tuple[int, int]
    file_identities: tuple[tuple[int, int], ...]


@dataclass
class LocalStageAttempt:
    request: PreparationRequest
    state: str = "pending"
    partial_directory: str | None = None
    output_directory: str | None = None
    receipt: LocalStageReceipt | None = None


def _write_complete(directory_fd: int, name: str, data: bytes, checkpoint: Callable[[], None]):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
    try:
        remaining = memoryview(data)
        while remaining:
            checkpoint()
            written = os.write(fd, remaining[:1024 * 1024])
            if written <= 0:
                raise OSError("Local staging write made no progress.")
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _verify_files(directory_fd: int, payloads: tuple[bytes, bytes, bytes]):
    identities = []
    def signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    for name, expected in zip(_FILES, payloads, strict=True):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Local staging output is not a regular file.")
            actual = bytearray()
            while len(actual) <= len(expected):
                chunk = os.read(fd, min(1024 * 1024, len(expected) + 1 - len(actual)))
                if not chunk:
                    break
                actual.extend(chunk)
            if actual != expected:
                raise ValueError("Local staging bytes changed or were incomplete.")
            if (signature(before) != signature(os.fstat(fd))
                    or signature(before) != signature(os.stat(name, dir_fd=directory_fd, follow_symlinks=False))):
                raise ValueError("Local staging output changed while verifying.")
            identities.append((before.st_dev, before.st_ino))
        finally:
            os.close(fd)
    return tuple(identities)


class LocalMotionStager:
    def __init__(self, output_root: Path):
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise RuntimeError("Local staging requires POSIX directory descriptors and no-follow opens.")
        if output_root.is_symlink():
            raise ValueError("Local staging root must not be a symlink.")
        if ".." in output_root.parts:
            raise ValueError("Local staging root must not contain parent traversal.")
        self.root = output_root.resolve(strict=True)
        self._root_fd = os.open(self.root, _DIRECTORY_FLAGS)
        self._lock = threading.RLock()
        self._attempts: dict[str, LocalStageAttempt] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        with self._lock:
            if self._root_fd is not None:
                os.close(self._root_fd)
                self._root_fd = None

    def inspect(self, operation_id: str) -> LocalStageAttempt | None:
        with self._lock:
            return deepcopy(self._attempts.get(operation_id))

    def _check_root(self):
        if self._root_fd is None:
            raise RuntimeError("Local staging root has been closed.")
        current = self.root.stat(follow_symlinks=False)
        opened = os.fstat(self._root_fd)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Local staging root identity changed.")

    @staticmethod
    def _directory(request: PreparationRequest) -> str:
        encoded = json.dumps([request.operation_id, request.project_id, request.scene_id, request.line_id],
                             ensure_ascii=False, separators=(",", ":")).encode()
        return "prepared-" + hashlib.sha256(encoded).hexdigest()

    def stage(self, request: PreparationRequest, bundle: PreparedBundle, checkpoint: Callable[[], None]) -> str:
        with self._lock:
            previous = self._attempts.get(request.operation_id)
            if previous and previous.request != request:
                raise ValueError("Local staging operation identity belongs to another source.")
            self._admit(previous, checkpoint)
            bundle = deepcopy(bundle)
            source = bundle.snapshot.source
            if (source.project_id, source.scene_id, source.line_id) != (request.project_id, request.scene_id, request.line_id):
                raise ValueError("Local staging source differs from the request.")
            if assemble_bundle(bundle.snapshot, bundle.audio, bundle.lab) != bundle:
                raise ValueError("Local staging bundle metadata or TXT differs from its validated media.")
            if previous:
                return self._replay(previous, request, bundle, checkpoint)
            attempt = LocalStageAttempt(request)
            self._attempts[request.operation_id] = attempt
            try:
                return self._stage_once(attempt, bundle, checkpoint)
            except PreparationCancelled:
                attempt.state = "cancelled"
                raise
            except Exception:
                attempt.state = "failed"
                raise

    def verify(self, request: PreparationRequest, bundle: PreparedBundle, token: str,
               checkpoint: Callable[[], None]) -> None:
        """Read-only receipt admission; never republish or infer readiness from paths."""
        with self._lock:
            attempt = self._attempts.get(request.operation_id)
            self._admit(attempt, checkpoint)
            try:
                if attempt is None or attempt.receipt is None or token != attempt.receipt.token:
                    raise ValueError("Local staging receipt is unknown or mismatched.")
                if assemble_bundle(bundle.snapshot, bundle.audio, bundle.lab) != bundle:
                    raise ValueError("Local staging receipt bundle is inconsistent.")
                self._replay(attempt, request, bundle, checkpoint)
            except PreparationCancelled:
                if attempt:
                    attempt.state = "cancelled"
                raise
            except Exception:
                if attempt:
                    attempt.state = "failed"
                raise

    def _admit(self, previous, checkpoint):
        try:
            self._check_root()
            checkpoint()
        except PreparationCancelled:
            if previous:
                previous.state = "cancelled"
            raise
        except Exception:
            if previous:
                previous.state = "failed"
            raise

    def _replay(self, attempt, request, bundle, checkpoint):
        if attempt.request != request:
            raise ValueError("Local staging operation identity belongs to another source.")
        if attempt.state != "staged":
            raise PreparationStopped("Local staging attempt needs reconciliation before retry.")
        if attempt.receipt.content_version != bundle.content_version:
            raise ValueError("Local staging cannot reuse a request for changed content.")
        try:
            receipt = attempt.receipt
            payloads = (bundle.audio.wav, bundle.dialogue_txt, bundle.lab.content)
            directory = self._directory(request)
            expected_token = "scena-local-stage:" + directory.removeprefix("prepared-")
            if (receipt.request != request or receipt.directory != directory
                    or attempt.output_directory != directory or receipt.token != expected_token
                    or receipt.digests != tuple(hashlib.sha256(data).hexdigest() for data in payloads)):
                raise ValueError("Local staging receipt identity/content is inconsistent.")
            fd = os.open(directory, _DIRECTORY_FLAGS, dir_fd=self._root_fd)
            try:
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino) != receipt.directory_identity:
                    raise ValueError("Local staging output directory was replaced.")
                if _verify_files(fd, payloads) != receipt.file_identities:
                    raise ValueError("Local staging output files were replaced.")
                current = os.stat(directory, dir_fd=self._root_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) != receipt.directory_identity:
                    raise ValueError("Local staging output directory changed while verifying.")
                checkpoint()
                self._check_root()
            finally:
                os.close(fd)
            return attempt.receipt.token
        except PreparationCancelled:
            attempt.state = "cancelled"
            raise
        except Exception:
            attempt.state = "failed"
            raise

    def _stage_once(self, attempt, bundle, checkpoint):
        payloads = (bundle.audio.wav, bundle.dialogue_txt, bundle.lab.content)
        directory = self._directory(attempt.request)
        try:
            os.stat(directory, dir_fd=self._root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("Local staging output already exists; no overwrite or restart adoption.")
        partial = ".partial-" + uuid4().hex
        os.mkdir(partial, 0o700, dir_fd=self._root_fd)
        attempt.partial_directory = partial
        fd = os.open(partial, _DIRECTORY_FLAGS, dir_fd=self._root_fd)
        try:
            attempt.state = "writing"
            for name, data in zip(_FILES, payloads, strict=True):
                _write_complete(fd, name, data, checkpoint)
            _verify_files(fd, payloads)
            checkpoint()
            self._check_root()
            os.mkdir(directory, 0o700, dir_fd=self._root_fd)
            attempt.output_directory = directory
            output_fd = os.open(directory, _DIRECTORY_FLAGS, dir_fd=self._root_fd)
            try:
                attempt.state = "publishing"
                for name in _FILES:
                    checkpoint()
                    os.link(name, name, src_dir_fd=fd, dst_dir_fd=output_fd, follow_symlinks=False)
                identities = _verify_files(output_fd, payloads)
                checkpoint()
                self._check_root()
                receipt = LocalStageReceipt(
                    attempt.request, "scena-local-stage:" + directory.removeprefix("prepared-"), directory,
                    bundle.content_version, tuple(hashlib.sha256(data).hexdigest() for data in payloads),
                    (os.fstat(output_fd).st_dev, os.fstat(output_fd).st_ino), identities,
                )
                # Only owned, successfully linked fixture clones are cleaned.
                for name in _FILES:
                    os.unlink(name, dir_fd=fd)
                os.rmdir(partial, dir_fd=self._root_fd)
                attempt.partial_directory = None
                attempt.receipt, attempt.state = receipt, "staged"
                return receipt.token
            finally:
                os.close(output_fd)
        finally:
            os.close(fd)

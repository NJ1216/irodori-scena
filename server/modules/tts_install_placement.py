"""Platform-specific placement for managed TTS runtime directories."""
from __future__ import annotations

import shutil
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from server.platform_support import environment_python

WINDOWS_RETRY_ATTEMPTS = 5
WINDOWS_RETRY_DELAY_SECONDS = 0.1


def is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform) == "win32"


def _sharing_violation(error: OSError) -> bool:
    return isinstance(error, PermissionError) or getattr(error, "winerror", None) in {5, 32}


def retry_windows_file_operation(operation: Callable[[], None], *, attempts: int = WINDOWS_RETRY_ATTEMPTS,
                                 delay: float = WINDOWS_RETRY_DELAY_SECONDS) -> None:
    for attempt in range(attempts):
        try:
            operation()
            return
        except OSError as error:
            if not _sharing_violation(error) or attempt + 1 == attempts:
                raise
            time.sleep(delay)


def remove_windows_incomplete(path: Path) -> None:
    if path.exists():
        retry_windows_file_operation(lambda: shutil.rmtree(path))


def engine_environment_path(staging: Path, target: Path, platform: str | None = None) -> Path:
    if not is_windows(platform):
        return staging
    remove_windows_incomplete(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def validate_engine_source(path: Path, dependency_lock_sha256: str, sha256: Callable[[Path], str]) -> None:
    if not (path / "infer.py").is_file() or not (path / "uv.lock").is_file():
        raise ValueError("エンジンの必須ファイルが不足しています。")
    if sha256(path / "uv.lock") != dependency_lock_sha256:
        raise ValueError("エンジンの依存lockが一致しません。")


def validate_environment(path: Path) -> None:
    if not environment_python(path).is_file():
        raise ValueError("Python環境の実行ファイルが不足しています。")


def place_windows_directory(source: Path, target: Path, validate: Callable[[Path], None]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    remove_windows_incomplete(target)
    temporary = target.parent / f".{target.name}.install-{uuid.uuid4().hex}"
    try:
        shutil.copytree(source, temporary)
        validate(temporary)
        retry_windows_file_operation(lambda: temporary.replace(target))
    except BaseException:
        remove_windows_incomplete(temporary)
        raise


def rollback_windows_engine(engine: Path, environment: Path) -> None:
    first_error: OSError | None = None
    for path in (engine, environment):
        try:
            remove_windows_incomplete(path)
        except OSError as error:
            first_error = first_error or error
    if first_error:
        raise first_error

"""Remove release-owned per-user data for the Windows uninstaller."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Callable, Protocol

KEYCHAIN_SERVICE = "com.irodori-scena.llm-api-key"
HF_ACCOUNT = "huggingface-token"
DIRECTORY_DELETE_ATTEMPTS = 5
DIRECTORY_DELETE_RETRY_SECONDS = 0.25


class CredentialBackend(Protocol):
    def delete_password(self, service: str, account: str) -> None: ...


def _remove_tree(root: Path) -> None:
    def retry_readonly(operation, path: str, error: BaseException) -> None:
        try:
            os.chmod(path, stat.S_IWRITE)
            operation(path)
        except Exception:
            raise error

    shutil.rmtree(root, onexc=retry_readonly)


def _json_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _legacy_account(settings: dict[str, object]) -> str | None:
    if not any(key in settings for key in ("provider", "baseUrl", "apiKeyEnabled")):
        return None
    provider = str(settings.get("provider", "")).strip()
    base_url = str(settings.get("baseUrl", "")).strip().rstrip("/").lower()
    digest = hashlib.sha256(f"{provider}\n{base_url}".encode()).hexdigest()
    return f"endpoint-{digest}"


def credential_accounts(data_root: Path) -> tuple[str, ...]:
    accounts = {HF_ACCOUNT}
    registry = _json_object(data_root / "llm-registry.json")
    endpoints = registry.get("endpoints", [])
    if isinstance(endpoints, list):
        for endpoint in endpoints:
            if isinstance(endpoint, dict) and endpoint.get("id"):
                accounts.add(f"llm-endpoint-{endpoint['id']}")
    legacy = _legacy_account(_json_object(data_root / "connection-settings.json"))
    if legacy:
        accounts.add(legacy)
    return tuple(sorted(accounts))


def cleanup_user_data(
    data_root: Path,
    webview_root: Path,
    credential_backend: CredentialBackend,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Delete credentials first, then release roots; return every failure."""
    failures: list[str] = []
    password_delete_error = getattr(getattr(credential_backend, "errors", None), "PasswordDeleteError", ())
    for account in credential_accounts(data_root):
        try:
            credential_backend.delete_password(KEYCHAIN_SERVICE, account)
        except password_delete_error:
            pass
        except Exception as error:  # The uninstaller must expose backend failures.
            failures.append(f"credential {account}: {error}")
    if failures:
        return failures
    for root in (data_root, webview_root):
        for attempt in range(DIRECTORY_DELETE_ATTEMPTS):
            try:
                if root.exists():
                    _remove_tree(root)
                break
            except Exception as error:
                if attempt + 1 == DIRECTORY_DELETE_ATTEMPTS:
                    failures.append(f"directory {root}: {error}")
                else:
                    sleep(DIRECTORY_DELETE_RETRY_SECONDS)
    return failures


def run_cleanup(error_log: str | None = None) -> int:
    import keyring

    appdata = os.environ.get("APPDATA")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if not appdata or not local_appdata:
        failures = ["current user's APPDATA directories are unavailable"]
        _write_error_log(error_log, failures)
        return 2
    data_root = (Path(appdata) / "irodori-SCENA").resolve()
    webview_root = (Path(local_appdata) / "com.irodori-scena").resolve()
    failures = cleanup_user_data(data_root, webview_root, keyring)
    if failures:
        _write_error_log(error_log, failures)
        return 1
    if error_log:
        Path(error_log).unlink(missing_ok=True)
    return 0


def _write_error_log(error_log: str | None, failures: list[str]) -> None:
    if not error_log:
        return
    try:
        Path(error_log).write_text("\n".join(failures) + "\n", encoding="utf-8")
    except OSError:
        pass

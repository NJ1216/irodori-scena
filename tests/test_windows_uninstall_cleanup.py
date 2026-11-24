from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from server.windows_uninstall_cleanup import KEYCHAIN_SERVICE, cleanup_user_data, run_cleanup


class MissingCredential(Exception):
    pass


class FakeCredentials:
    class errors:
        PasswordDeleteError = MissingCredential

    def __init__(self, accounts: set[str], fail_once: str | None = None):
        self.accounts = accounts
        self.fail_once = fail_once
        self.deleted: list[tuple[str, str]] = []

    def delete_password(self, service: str, account: str) -> None:
        self.deleted.append((service, account))
        if account == self.fail_once:
            self.fail_once = None
            raise RuntimeError("credential store locked")
        if account not in self.accounts:
            raise MissingCredential(account)
        self.accounts.remove(account)


class WindowsUninstallCleanupTests(unittest.TestCase):
    def roots(self, parent: Path) -> tuple[Path, Path, Path]:
        data = parent / "irodori-SCENA"
        webview = parent / "com.irodori-scena"
        external = parent / "exports" / "story.scena"
        data.mkdir()
        webview.mkdir()
        external.parent.mkdir()
        external.write_text("keep", encoding="utf-8")
        (data / "managed-model.bin").write_bytes(b"model")
        (webview / "Local Storage").write_text("state", encoding="utf-8")
        return data, webview, external

    def test_removes_all_managed_roots_and_credentials_but_keeps_external_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data, webview, external = self.roots(Path(directory))
            (data / "llm-registry.json").write_text(
                json.dumps({"endpoints": [{"id": "remote"}, {"id": "second"}]}), encoding="utf-8"
            )
            (data / "connection-settings.json").write_text(
                json.dumps({"provider": "openai", "baseUrl": "https://example.test/v1/", "apiKeyEnabled": True}),
                encoding="utf-8",
            )
            accounts = {"huggingface-token", "llm-endpoint-remote", "llm-endpoint-second"}
            backend = FakeCredentials(set(accounts))
            failures = cleanup_user_data(data, webview, backend)
            self.assertEqual(failures, [])
            self.assertFalse(data.exists())
            self.assertFalse(webview.exists())
            self.assertEqual(external.read_text(encoding="utf-8"), "keep")
            self.assertTrue(
                accounts.issubset({account for service, account in backend.deleted if service == KEYCHAIN_SERVICE})
            )
            self.assertTrue(any(account.startswith("endpoint-") for _, account in backend.deleted))

    def test_missing_or_truncated_metadata_is_safe_and_missing_roots_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "irodori-SCENA"
            data.mkdir()
            (data / "llm-registry.json").write_text('{"endpoints":[{"id":"cut', encoding="utf-8")
            backend = FakeCredentials(set())
            self.assertEqual(cleanup_user_data(data, Path(directory) / "missing", backend), [])
            self.assertFalse(data.exists())

    def test_credential_failure_preserves_data_and_retry_completes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data, webview, _ = self.roots(Path(directory))
            (data / "llm-registry.json").write_text(json.dumps({"endpoints": [{"id": "remote"}]}), encoding="utf-8")
            backend = FakeCredentials({"huggingface-token", "llm-endpoint-remote"}, fail_once="llm-endpoint-remote")
            self.assertTrue(cleanup_user_data(data, webview, backend))
            self.assertTrue(data.exists())
            self.assertTrue(webview.exists())
            self.assertEqual(cleanup_user_data(data, webview, backend), [])
            self.assertFalse(data.exists())
            self.assertFalse(webview.exists())

    def test_transient_directory_failure_is_retried_internally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data, webview, _ = self.roots(Path(directory))
            backend = FakeCredentials(set())
            real_rmtree = __import__("shutil").rmtree
            failed = False

            def fail_once(path: Path, **options) -> None:
                nonlocal failed
                if Path(path) == data and not failed:
                    failed = True
                    raise PermissionError("in use")
                real_rmtree(path, **options)

            with patch("server.windows_uninstall_cleanup.shutil.rmtree", side_effect=fail_once):
                failures = cleanup_user_data(data, webview, backend, sleep=lambda _: None)
            self.assertEqual(failures, [])
            self.assertFalse(data.exists())

    def test_persistent_directory_failure_is_reported_for_user_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data, webview, _ = self.roots(Path(directory))
            backend = FakeCredentials(set())
            with patch("server.windows_uninstall_cleanup.shutil.rmtree", side_effect=PermissionError("in use")):
                failures = cleanup_user_data(data, webview, backend, sleep=lambda _: None)
            self.assertTrue(any("in use" in failure for failure in failures))
            self.assertTrue(data.exists())
            self.assertTrue(webview.exists())

    @patch("server.windows_uninstall_cleanup.cleanup_user_data", return_value=[])
    def test_cli_derives_fixed_release_roots_from_the_process_user(self, cleanup) -> None:
        with tempfile.TemporaryDirectory() as directory:
            error_log = Path(directory) / "failure.log"
            with patch.dict(
                "os.environ",
                {"APPDATA": "C:/Users/test/AppData/Roaming", "LOCALAPPDATA": "C:/Users/test/AppData/Local"},
            ):
                self.assertEqual(run_cleanup(str(error_log)), 0)
            cleanup.assert_called_once_with(
                Path("C:/Users/test/AppData/Roaming/irodori-SCENA").resolve(),
                Path("C:/Users/test/AppData/Local/com.irodori-scena").resolve(),
                ANY,
            )

    @patch("server.windows_uninstall_cleanup.cleanup_user_data", return_value=[])
    def test_cli_fails_closed_when_user_appdata_is_unavailable(self, cleanup) -> None:
        with tempfile.TemporaryDirectory() as directory:
            error_log = Path(directory) / "failure.log"
            with patch.dict("os.environ", {"APPDATA": "", "LOCALAPPDATA": ""}):
                self.assertEqual(run_cleanup(str(error_log)), 2)
            self.assertIn("unavailable", error_log.read_text(encoding="utf-8"))
        cleanup.assert_not_called()


if __name__ == "__main__":
    unittest.main()

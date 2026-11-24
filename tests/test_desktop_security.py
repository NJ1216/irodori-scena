from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response
from fastapi.testclient import TestClient

from server.application import create_base_app


class DesktopSecurityTests(unittest.TestCase):
    def test_desktop_requires_a_startup_token(self) -> None:
        with patch.dict(os.environ, {"SCENA_DESKTOP": "1", "SCENA_PARENT_PID": str(os.getpid())}, clear=False):
            with patch.dict(os.environ, {"SCENA_API_TOKEN": ""}, clear=False):
                with self.assertRaisesRegex(RuntimeError, "SCENA_API_TOKEN"):
                    create_base_app()

    def test_desktop_api_uses_bearer_auth_but_options_does_not(self) -> None:
        environment = {
            "SCENA_DESKTOP": "1",
            "SCENA_API_TOKEN": "a" * 64,
            "SCENA_PARENT_PID": str(os.getpid()),
            "SCENA_CONTROL_ADDRESS": "127.0.0.1:49152",
        }
        with patch.dict(os.environ, environment, clear=False):
            application = create_base_app()
            application.get("/api/probe")(lambda: {"ok": True})
            client = TestClient(application)
            self.assertEqual(client.get("/api/probe").status_code, 401)
            self.assertEqual(client.get("/api/probe", headers={"Authorization": f"Bearer {environment['SCENA_API_TOKEN']}"}).status_code, 200)
            self.assertNotEqual(client.options("/api/probe").status_code, 401)

    def test_browser_mode_remains_unauthenticated(self) -> None:
        with patch.dict(os.environ, {"SCENA_DESKTOP": "0"}, clear=False):
            application = create_base_app()
            application.get("/api/probe")(lambda: {"ok": True})
            self.assertEqual(TestClient(application).get("/api/probe").status_code, 200)

    def test_cors_exposes_history_scope_to_the_ui(self) -> None:
        application = create_base_app()

        @application.get("/api/probe")
        def probe(response: Response) -> dict[str, bool]:
            response.headers["X-SCENA-History-Scope"] = "characters"
            return {"ok": True}

        response = TestClient(application).get("/api/probe", headers={"Origin": "tauri://localhost"})
        self.assertIn(
            "X-SCENA-History-Scope",
            response.headers["access-control-expose-headers"],
        )

    def test_unhandled_api_error_is_logged_and_returned_safely_with_cors(self) -> None:
        application = create_base_app()

        @application.get("/api/failure")
        def fail() -> None:
            raise RuntimeError("private path: C:/Users/example/secret.json")

        with patch("server.application.LOGGER.exception") as logged:
            response = TestClient(application, raise_server_exceptions=False).get(
                "/api/failure", headers={"Origin": "tauri://localhost"},
            )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json(), {"detail": {
            "code": "internal_server_error",
            "message": "アプリ内部の処理エラーが発生しました。",
        }})
        self.assertEqual(response.headers["access-control-allow-origin"], "tauri://localhost")
        self.assertNotIn("secret.json", response.text)
        logged.assert_called_once()

    def test_http_errors_keep_their_existing_response(self) -> None:
        application = create_base_app()

        @application.get("/api/expected-error")
        def fail() -> None:
            raise HTTPException(status_code=409, detail="expected conflict")

        response = TestClient(application, raise_server_exceptions=False).get("/api/expected-error")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"detail": "expected conflict"})


if __name__ == "__main__":
    unittest.main()

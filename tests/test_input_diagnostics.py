from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server.app  # noqa: F401
from server.application import create_base_app
from server.input_diagnostics import safe_validation_issues
from server.modules.public_llm_models import AiJobApiRequest


class InputDiagnosticsTests(unittest.TestCase):
    def test_development_logs_constraint_without_submitted_text(self) -> None:
        with patch.dict(os.environ, {"SCENA_DESKTOP": "0", "SCENA_DEV_MODE": "1"}):
            application = create_base_app()

        @application.post("/api/ai/jobs")
        def start(request: AiJobApiRequest):
            return {"ok": True}

        with self.assertLogs("uvicorn.error", level="WARNING") as logs:
            response = TestClient(application).post("/api/ai/jobs", json={
                "mode": "draft", "character_ids": ["private-cast"], "theme": "秘密" * 2001,
            }, headers={"Authorization": "Bearer private-token", "Origin": "http://localhost:5175"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5175")
        output = " ".join(logs.output)
        self.assertIn("theme", output)
        self.assertIn("string_too_long", output)
        for secret in ("秘密", "private-cast", "private-token"):
            self.assertNotIn(secret, output)

    def test_unknown_keys_and_model_error_values_are_redacted(self) -> None:
        result = safe_validation_issues([{
            "loc": ("body", "private-key"), "type": "extra_forbidden", "input": "private-input",
        }, {
            "loc": ("body",), "type": "value_error",
            "msg": "Value error, allowed_emojis contains unsupported emoji: private-value",
            "ctx": {"error": ValueError("private-value")},
        }])
        self.assertNotIn("private", str(result))
        self.assertEqual(result[1]["constraint"], "unsupported_emoji")

    def test_production_does_not_install_diagnostics(self) -> None:
        with patch.dict(os.environ, {"SCENA_DESKTOP": "0", "SCENA_DEV_MODE": "0"}):
            with patch("server.application.install_input_diagnostics") as install:
                create_base_app()
        install.assert_not_called()

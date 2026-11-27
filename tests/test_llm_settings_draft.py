"""Exercise persisted settings and request validation without replacing the resolver."""
from __future__ import annotations

import scena_test_isolation  # noqa: F401
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app import app
from server.modules import runtime_state, llm_registry
from server.modules.public_llm_models import AiJobApiRequest


class LlmSettingsDraftTests(unittest.TestCase):
    def test_short_themes_are_preserved_without_padding_or_rewriting(self) -> None:
        for theme in ("春", "雑談", "自己紹介", " 自己紹介\n", "あ" * 4000):
            with self.subTest(length=len(theme)):
                request = AiJobApiRequest(mode="draft", character_ids=["cast-1"], theme=theme)
                self.assertEqual(request.theme, theme)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.enterContext(patch.object(llm_registry, "REGISTRY_FILE", Path(temporary.name) / "registry.json"))
        self.enterContext(patch.object(llm_registry.keyring, "get_password", return_value=None))
        self.enterContext(patch("server.modules.local_llm_runtime.local_llm_status", return_value={}))
        self.enterContext(patch.object(runtime_state, "DRAFT_JOBS", {}))
        self.enterContext(patch("server.modules.project_repository.read_project", return_value={
            "title": "", "characters": [{"id": "cast-1", "name": "彩"}],
        }))
        self.client = TestClient(app, raise_server_exceptions=False)
        self.payload = {"mode": "draft", "character_ids": ["cast-1"], "theme": "自己紹介"}

    def add_model(self, model: str) -> str:
        response = self.client.post("/api/llm/remote/settings", json={
            "provider": "ollama", "baseUrl": "http://127.0.0.1:11434/v1", "modelId": model,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["registry"]["cards"][-1]["id"]

    def test_new_ollama_setting_becomes_default_and_reaches_draft_worker(self) -> None:
        self.add_model("old-model")
        card_id = self.add_model("gemma4:12b-mlx")
        selected = self.client.get("/api/llm/registry")
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(selected.json()["defaultCardId"], card_id)
        received = []
        ready = Event()

        def worker(_job_id, request, characters):
            received.append((request, characters))
            ready.set()

        with patch("server.modules.draft_jobs.run_draft_job", side_effect=worker):
            response = self.client.post("/api/ai/jobs", json=self.payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(ready.wait(2))
        request, characters = received[0]
        self.assertEqual((request.provider, request.base_url, request.model),
                         ("ollama", "http://127.0.0.1:11434/v1", "gemma4:12b-mlx"))
        self.assertEqual(characters, [{"id": "cast-1", "name": "彩"}])
        self.assertEqual(request.theme, "自己紹介")
        self.assertEqual(response.json()["provider"], "ollama")

    def test_invalid_draft_is_a_cors_readable_input_error_before_start(self) -> None:
        self.add_model("gemma4:12b-mlx")
        invalid = [
            {"theme": ""}, {"theme": " \n　"}, {"character_ids": []}, {"speech_rate": True},
            {"performance_speech_rate_min": 1.5, "performance_speech_rate_max": 1},
            {"allowed_emojis": ["🚀"]},
        ]
        with patch("server.modules.draft_jobs.run_draft_job") as worker:
            for values in invalid:
                with self.subTest(values=values):
                    response = self.client.post("/api/ai/jobs", json={**self.payload, **values},
                                                headers={"Origin": "http://localhost:5175"})
                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(response.headers.get("access-control-allow-origin"), "http://localhost:5175")
                    self.assertIsInstance(response.json()["detail"], list)
            worker.assert_not_called()
        self.assertEqual(runtime_state.DRAFT_JOBS, {})

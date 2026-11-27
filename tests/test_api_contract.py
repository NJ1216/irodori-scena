from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.app import app, create_app, default_project


FIXTURES = Path(__file__).with_name("fixtures")


class ApiContractTests(unittest.TestCase):
    def test_voice_design_suggestion_allows_emotion_text_object(self) -> None:
        suggestion = {
            "voiceKeywords": "落ち着いた声",
            "baselineText": "こんにちは。よろしくお願いします。",
            "emotionTexts": {
                "normal": "こんにちは。",
                "joy": "嬉しいです。",
                "anger": "困ります。",
                "sorrow": "寂しいです。",
                "delight": "楽しいです。",
            },
        }
        with patch("server.modules.suggestions.suggest_voice_design_completion", return_value=suggestion):
            response = self.client.post(
                "/api/characters/voice-design-suggestion",
                json={"keywords": "落ち着いた声"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), suggestion)

    def test_voice_design_save_rejects_incomplete_emotion_candidates(self) -> None:
        response = self.client.post(
            "/api/characters/voice-design/save",
            json={
                "baseline_candidate_id": "baseline-1",
                "emotion_candidate_ids": {
                    "normal": "normal-1",
                    "joy": "joy-1",
                    "anger": "anger-1",
                    "sorrow": "sorrow-1",
                },
                "name": "彩",
                "voice_keywords": "落ち着いた声",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)

    def test_voice_design_save_accepts_a_baseline_without_emotion_candidates(self) -> None:
        from server.modules.models import SaveVoiceDesignRequest

        request = SaveVoiceDesignRequest(
            baseline_candidate_id="baseline-1",
            name="彩",
            voice_keywords="男",
            voice_design={"gender": "男性", "qualities": ["太い"], "notes": ""},
        )
        self.assertEqual(request.emotion_candidate_ids, {})
        self.assertEqual(request.voice_keywords, "男")
        self.assertEqual(request.voice_design.gender, "男性")

    def test_voice_design_reference_import_accepts_emotion_metadata(self) -> None:
        from server.modules.models import ImportVoiceDesignReferenceRequest

        request = ImportVoiceDesignReferenceRequest(
            audio_base64="A" * 16,
            kind="emotion",
            emotion="joy",
            reference_candidate_id="baseline-1",
        )
        self.assertEqual(request.kind, "emotion")
        self.assertEqual(request.emotion, "joy")
        self.assertEqual(request.reference_candidate_id, "baseline-1")

    def test_voice_design_reference_import_requires_a_baseline_for_emotions(self) -> None:
        from pydantic import ValidationError
        from server.modules.models import ImportVoiceDesignReferenceRequest

        with self.assertRaises(ValidationError):
            ImportVoiceDesignReferenceRequest(audio_base64="A" * 16, kind="emotion", emotion="joy")

    def test_ai_job_contract_supports_draft_and_direction_modes(self) -> None:
        def selected_llm(request):
            return request.model_copy(update={"provider": "scena-local", "model": "mlx-community/gemma-4-31b"})

        payloads = (
            {
                "mode": "direction",
                "line_ids": ["line-1"],
                "emoji_expressions": False,
                "direction_speech_rate": False,
                "gap_seconds": False,
                "stage_direction": True,
            },
            {
                "mode": "draft",
                "character_ids": ["cast-1"],
                "target_minutes": 1,
                "theme": "単一APIの台本生成を確認するテストです。",
                "simultaneous_cues": False,
                "overlapping_speech": True,
            },
        )
        with (
            patch("server.modules.ai_direction.run_ai_direction"),
            patch("server.modules.draft_jobs.run_draft_job"),
            patch("server.modules.local_llm_runtime.resolve_logical_llm_request", side_effect=selected_llm),
            patch(
                "server.modules.project_repository.read_project",
                return_value={"title": "", "characters": [{"id": "cast-1"}]},
            ),
            patch("server.modules.inference.find_character", return_value={"id": "cast-1", "name": "彩"}),
        ):
            for payload in payloads:
                started = self.client.post("/api/ai/jobs", json=payload)
                self.assertEqual(started.status_code, 200, started.text)
                job = started.json()
                self.assertEqual(job["mode"], payload["mode"])
                self.assertEqual((job["provider"], job["model"]), ("scena-local", "mlx-community/gemma-4-31b"))
                self.assertEqual(self.client.get(f"/api/ai/jobs/{job['id']}").status_code, 200)
                cancelled = self.client.post(f"/api/ai/jobs/{job['id']}/cancel")
                self.assertEqual(cancelled.status_code, 200, cancelled.text)
                self.assertEqual(cancelled.json()["status"], "cancelled")
        from server.modules.models import AiJobRequest

        draft_request = AiJobRequest.model_validate(payloads[1]).draft_request()
        self.assertTrue(draft_request.overlapping_speech)
        self.assertFalse(draft_request.simultaneous_cues)
        self.assertIn("overlapping_speech", app.openapi()["components"]["schemas"]["AiJobApiRequest"]["properties"])

    def test_create_app_accepts_dependency_overrides(self) -> None:
        def dependency() -> str:
            return "default"

        def replacement() -> str:
            return "test"

        created = create_app(dependency_overrides={dependency: replacement})
        try:
            self.assertIs(created, app)
            self.assertIs(created.dependency_overrides[dependency], replacement)
        finally:
            created.dependency_overrides.pop(dependency, None)

    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)
        cls.project = json.loads((FIXTURES / "project-contract.json").read_text())
        cls.openapi_contract = json.loads((FIXTURES / "openapi-contract.json").read_text())

    def test_openapi_route_and_schema_contract(self) -> None:
        routes = sorted(
            [method, route.path]
            for route in app.routes
            if route.path.startswith(("/api", "/media", "/global-media"))
            for method in sorted(route.methods or ())
        )
        schemas = sorted(app.openapi()["components"]["schemas"])
        self.assertEqual(routes, sorted(self.openapi_contract["routes"]))
        self.assertEqual(schemas, self.openapi_contract["schemas"])

    def test_public_ai_requests_reject_transport_overrides(self) -> None:
        response = self.client.post(
            "/api/drafts/theme-suggestion",
            json={
                "theme": "十分に長いテーマです",
                "character_ids": ["cast"],
                "base_url": "https://attacker.invalid/v1",
                "model": "override",
                "api_key": "secret",
                "provider": "openai",
            },
        )
        self.assertEqual(response.status_code, 422)

        script_response = self.client.post(
            "/api/lines/assistant/jobs",
            json={
                "operation": "rewrite",
                "line_ids": ["line-1"],
                "character_ids": ["cast"],
                "base_url": "https://attacker.invalid/v1",
            },
        )
        self.assertEqual(script_response.status_code, 422)

    def test_theme_suggestion_duration_openapi_contract(self) -> None:
        schema = app.openapi()["components"]["schemas"]["ThemeSuggestionApiRequest"]
        duration = schema["properties"]["target_minutes"]
        self.assertEqual(duration["default"], 3)
        self.assertEqual((duration["minimum"], duration["maximum"]), (1, 60))

    def test_default_project_keeps_persisted_shape_and_quality_defaults(self) -> None:
        project = default_project()
        self.assertEqual(project["version"], 1)
        self.assertRegex(project["id"], r"^project_[0-9a-f]{12}$")
        self.assertEqual(set(project), set(self.project))
        self.assertEqual(len(project["scenes"]), 1)
        self.assertEqual(len(project["scenes"][0]["lines"]), 1)
        self.assertEqual(
            {key: value for key, value in project["scenes"][0]["lines"][0].items() if key != "id"},
            {"characterId": "", "text": "", "stageDirection": "", "takes": [], "selectedTakeId": None},
        )
        self.assertEqual(
            project["settings"],
            {
                "speechRate": 1.2,
                "steps": 16,
                "textCfg": 3.0,
                "voiceCfg": 5.0,
                "captionCfg": 3.0,
                "seed": 0,
                "quality": "fast",
                "lineGap": 0.7,
                "llmBaseUrl": "http://127.0.0.1:11434/v1",
                "llmModel": "",
            },
        )

    def test_project_endpoint_preserves_json_keys_and_disables_caching(self) -> None:
        with patch("server.modules.project_repository.read_project", return_value=self.project):
            response = self.client.get("/api/project")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0")
        self.assertEqual(response.json(), self.project)

    def test_project_update_accepts_representative_persisted_json(self) -> None:
        with (
            patch("server.modules.export_service.active_export_job", return_value=None),
            patch("server.modules.project_repository.write_project", return_value=self.project) as write_project,
        ):
            response = self.client.put("/api/project", json={"project": self.project})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.project)
        write_project.assert_called_once_with(self.project, expected_revision=self.project["revision"])


if __name__ == "__main__":
    unittest.main()

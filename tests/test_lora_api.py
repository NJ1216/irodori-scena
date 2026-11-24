from __future__ import annotations
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from server import application  # noqa: F401
from server.modules import constants, lora_routes
from server.registry import deps
from test_lora_inputs import upload, wav_bytes


class LoraApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(constants, "TTS_ASSETS_ROOT", Path(self.temp.name))
        self.patch.start()
        self.client = TestClient(deps.app)

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_upload_review_keeps_unpaired_record_and_rejects_bad_request_fields(self):
        response = self.client.post("/api/lora/inputs", json={"files": [upload("voice.wav", wav_bytes(1))]})
        self.assertEqual(response.status_code, 200)
        row = response.json()["rows"][0]
        self.assertTrue(row["issues"])
        self.assertEqual(row["caption"], "")
        response = self.client.post("/api/lora/jobs", json={"datasetId": "x", "name": "x", "rows": [], "evil": 1})
        self.assertEqual(response.status_code, 422)

    def test_job_admission_failure_is_reported_without_accepted_job(self):
        from fastapi import HTTPException
        with patch.object(lora_routes, "start_job", side_effect=HTTPException(409, "busy")):
            response = self.client.post("/api/lora/jobs", json={"datasetId": "a" * 32, "name": "x",
                "rows": [{"id": "b" * 32, "text": "text", "caption": "", "speakerId": "speaker-1"}]})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/api/lora/jobs").json(), [])

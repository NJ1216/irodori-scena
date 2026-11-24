"""Ephemeral preview capture, cancellation and authenticated HTTP boundaries."""
import copy
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server import app as _app  # noqa: F401
from server.modules import lora_preview as preview
from test_lora_inputs import wav_bytes

SETTINGS = {"quality": "fast", "steps": 16, "speechRate": 1.2, "textCfg": 3, "voiceCfg": 5, "captionCfg": 3}
MIX = {"version": 1, "baseWeight": 10000, "entries": []}


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.reference = Path(self.temp.name) / "reference.wav"
        self.reference.write_bytes(wav_bytes(1))
        self.character = {"id": "cast", "referenceVersion": 2, "referenceFile": str(self.reference), "sampleText": "独自の台詞"}
        self.project = {"id": "project", "characters": [self.character], "scenes": [], "settings": SETTINGS}
        self.runtime = {"model": {"id": "fixed-runtime"}}
        self.stack = ExitStack()
        self.queue = []
        self.stack.enter_context(patch.object(preview, "launch_preview", side_effect=lambda *args: self.queue.append(args)))
        self.stack.enter_context(patch.object(preview, "supports_lora_model", return_value=True))
        self.dependencies = SimpleNamespace(require_tts_available=lambda: None, selected_tts_runtime=lambda: self.runtime,
            PROJECT_ROOT_LOCK=threading.RLock(), read_project=lambda: self.project,
            find_character=lambda project, identifier: self.character, new_id=lambda prefix: f"job-{len(self.queue)}",
            validate_take_wav=lambda path: 1, run_irodori=self.generate, app=preview.deps.app)
        self.stack.enter_context(patch.object(preview, "deps", self.dependencies))
        self.before = copy.deepcopy(self.project)
        self.calls = []

    def tearDown(self):
        preview.shutdown_previews()
        preview.JOBS.clear()
        self.stack.close()
        self.temp.cleanup()

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        kwargs["output"].write_bytes(wav_bytes(1))

    def request(self, **changes):
        return preview.PreviewRequest.model_validate({"characterId": "cast", "referenceVersion": 2, "loraMix": MIX, "settings": SETTINGS, **changes})

    def test_capture_reference_text_settings_and_base_without_persistence(self):
        started = preview.start_preview(self.request())
        self.assertEqual(started["status"], "generating")
        job, text, settings, adapter, runtime = self.queue[0]
        self.reference.write_bytes(b"changed after click")
        self.assertEqual((job["root"] / "reference.wav").read_bytes(), wav_bytes(1))
        self.runtime = {"model": {"id": "changed"}}
        preview._run(job, text, settings, adapter, runtime)
        self.assertEqual(job["status"], "failed")
        self.assertFalse(job["root"].exists())
        self.assertEqual(self.project, self.before)
        self.assertEqual(self.calls, [])

    def test_completed_preview_uses_fixed_seed_empty_caption_and_custom_text(self):
        started = preview.start_preview(self.request())
        preview._run(*self.queue[0])
        job = preview.get_preview(started["id"])
        call = self.calls[0]
        self.assertEqual(call["text"], "独自の台詞")
        self.assertEqual(call["seed"], 0)
        self.assertIsNone(call["caption"])
        self.assertEqual(call["generation_settings"], {**SETTINGS, "speechRate": 1.0})
        self.assertEqual(job["status"], "completed")
        self.assertTrue(Path(preview.preview_audio(job["id"]).path).is_file())
        self.assertEqual(self.project, self.before)
        preview.preview_cancel(job["id"])
        self.assertFalse(job["root"].exists())

    def test_client_speech_rate_does_not_change_preview_speed(self):
        for rate in (0.5, 1.0, 1.2, 2.0):
            with self.subTest(rate=rate):
                started = preview.start_preview(self.request(settings={**SETTINGS, "speechRate": rate}))
                preview._run(*self.queue[-1])
                self.assertEqual(self.calls[-1]["generation_settings"]["speechRate"], 1.0)
                self.assertEqual(self.project, self.before)
                preview.preview_cancel(started["id"])

    def test_fallback_cancel_after_inference_and_inference_error_leave_no_audio(self):
        self.character["sampleText"] = ""
        started = preview.start_preview(self.request())
        self.assertEqual(self.queue[0][1], preview.DEFAULT_SAMPLE_TEXT)
        def late(**kwargs):
            kwargs["output"].write_bytes(wav_bytes(1))
            preview.preview_cancel(started["id"])
        self.dependencies.run_irodori = late
        preview._run(*self.queue[0])
        job = preview.get_preview(started["id"])
        self.assertEqual(job["status"], "cancelled")
        self.assertIsNone(job["audioUrl"])
        self.assertFalse(job["root"].exists())
        self.dependencies.run_irodori = lambda **kwargs: (_ for _ in ()).throw(HTTPException(409, "inference busy"))
        failed = preview.start_preview(self.request())
        preview._run(*self.queue[-1])
        self.assertEqual(preview.get_preview(failed["id"])["error"], "inference busy")

    def test_missing_reference_changed_reference_and_unsupported_engine_are_rejected(self):
        with self.assertRaises(HTTPException):
            preview.start_preview(self.request(referenceVersion=1))
        self.reference.unlink()
        with self.assertRaises(HTTPException):
            preview.start_preview(self.request())
        with patch.object(preview, "supports_lora_model", return_value=False), self.assertRaises(HTTPException):
            preview.start_preview(self.request())
        self.assertEqual(self.queue, [])

    def test_job_conflict_and_cancel_before_inference(self):
        started = preview.start_preview(self.request())
        with self.assertRaises(HTTPException):
            preview.start_preview(self.request())
        preview.preview_cancel(started["id"])
        preview._run(*self.queue[0])
        self.assertEqual(self.calls, [])
        self.assertEqual(preview.get_preview(started["id"])["status"], "cancelled")

    def test_http_contract_rejects_local_paths_and_not_ready_audio(self):
        client = TestClient(preview.deps.app)
        response = client.post("/api/lora/previews", json=self.request().model_dump())
        self.assertEqual(response.status_code, 200, response.text)
        identifier = response.json()["id"]
        self.assertEqual(client.get(f"/api/lora/previews/{identifier}/audio").status_code, 409)
        payload = self.request().model_dump()
        payload["path"] = "/private/arbitrary.wav"
        self.assertEqual(client.post("/api/lora/previews", json=payload).status_code, 422)

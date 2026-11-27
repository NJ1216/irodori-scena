from __future__ import annotations
import scena_test_isolation  # noqa: F401
import base64
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from fastapi import HTTPException
from server.modules import constants
from server.modules.lora_inputs import stage_inputs, freeze_rows
from server.modules.lora_storage import owned_path


def wav_bytes(value: int, seconds: int = 1) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(value.to_bytes(2, "little", signed=True) * (48000 * seconds))
    return stream.getvalue()


def upload(name: str, data: bytes) -> dict:
    return {"name": name, "dataBase64": base64.b64encode(data).decode()}


class LoraInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patch = patch.object(constants, "TTS_ASSETS_ROOT", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_interleaved_pairs_retain_all_bytes_and_optional_caption(self):
        record = stage_inputs([upload("a.wav", wav_bytes(1)), upload("b.wav", wav_bytes(2)),
                               upload("a.txt", "一番".encode()), upload("b.txt", "二番".encode())])
        self.assertEqual([r["text"] for r in record["rows"]], ["一番", "二番"])
        target = self.root / "frozen"
        target.mkdir()
        rows = freeze_rows(record["datasetId"], record["rows"], target)
        self.assertEqual([r["caption"] for r in rows], ["", ""])
        self.assertEqual((target / rows[0]["wav"]).read_bytes(), wav_bytes(1))
        self.assertEqual((target / rows[1]["wav"]).read_bytes(), wav_bytes(2))

    def test_missing_text_manual_repair_and_unpaired_text_explicit_exclusion(self):
        record = stage_inputs([upload("a.wav", wav_bytes(1)), upload("b.wav", wav_bytes(2)), upload("orphan.txt", b"x")])
        target = self.root / "frozen"
        target.mkdir()
        with self.assertRaises(HTTPException):
            freeze_rows(record["datasetId"], record["rows"], target)
        edits = [{**row, "text": "修正", "excluded": row["wavName"] is None} for row in record["rows"]]
        self.assertEqual(len(freeze_rows(record["datasetId"], edits, target)), 2)

    def test_changed_frozen_audio_and_missing_row_fail_closed(self):
        record = stage_inputs([upload("a.wav", wav_bytes(1)), upload("b.wav", wav_bytes(2))])
        edits = [{**row, "text": "確認"} for row in record["rows"]]
        target = self.root / "frozen"
        target.mkdir()
        with self.assertRaises(HTTPException):
            freeze_rows(record["datasetId"], edits[:1], target)
        source = owned_path("inputs", record["datasetId"]) / record["rows"][0]["source"]["wav"]["file"]
        source.write_bytes(wav_bytes(3))
        with self.assertRaises(HTTPException) as caught:
            freeze_rows(record["datasetId"], edits, target)
        self.assertEqual(caught.exception.status_code, 409)

    def test_rejects_duplicate_and_traversal_without_retaining_partial_dataset(self):
        for files in ([upload("../x.wav", wav_bytes(1))], [upload("x.wav", wav_bytes(1)), upload("x.WAV", wav_bytes(2))]):
            with self.assertRaises(HTTPException):
                stage_inputs(files)
        self.assertEqual(list((self.root / "lora/inputs").iterdir()), [])

    def test_duration_admission_does_not_silently_crop_audio_or_transcript(self):
        record = stage_inputs([upload("a.wav", wav_bytes(1)), upload("b.wav", wav_bytes(2))])
        edits = [{**row, "text": "全文"} for row in record["rows"]]
        target = self.root / "frozen"
        target.mkdir()
        with self.assertRaises(HTTPException) as caught:
            freeze_rows(record["datasetId"], edits, target, max_seconds=0.9)
        self.assertIn("分割", caught.exception.detail)
        self.assertEqual(list(target.iterdir()), [])
        rows = freeze_rows(record["datasetId"], edits, target, max_seconds=1)
        self.assertEqual([row["text"] for row in rows], ["全文", "全文"])

    def test_truncated_pcm_is_review_error_and_cannot_start(self):
        record = stage_inputs([upload("a.wav", wav_bytes(1)[:-2]), upload("b.wav", wav_bytes(2))])
        self.assertIsNone(record["rows"][0]["durationSeconds"])
        target = self.root / "frozen"
        target.mkdir()
        edits = [{**row, "text": "本文"} for row in record["rows"]]
        with self.assertRaises(HTTPException):
            freeze_rows(record["datasetId"], edits, target)

    def test_automatic_duration_retains_ordinary_audio_without_short_diagnostic_split(self):
        record = stage_inputs([upload("a.wav", wav_bytes(1, 3)), upload("b.wav", wav_bytes(2, 4))])
        edits = [{**row, "text": "分割しない全文"} for row in record["rows"]]
        target = self.root / "frozen"
        target.mkdir()
        rows = freeze_rows(record["datasetId"], edits, target, max_seconds=None)
        self.assertEqual([row["durationSeconds"] for row in rows], [3, 4])
        self.assertEqual((target / rows[1]["wav"]).read_bytes(), wav_bytes(2, 4))
        self.assertEqual(rows[1]["text"], "分割しない全文")

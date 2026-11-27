from __future__ import annotations

import scena_test_isolation  # noqa: F401
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from server import application  # noqa: F401
from server.modules import constants, lora_folder_inputs as folders, lora_routes  # noqa: F401
from server.modules.lora_inputs import freeze_rows, input_audio_path
from server.modules.lora_storage import digest, owned_path, write_json
from server.registry import deps
from test_lora_inputs import wav_bytes


class LoraFolderInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source"
        self.source.mkdir()
        self.assets = self.root / "assets"
        self.patcher = patch.object(constants, "TTS_ASSETS_ROOT", self.assets)
        self.patcher.start()
        self.client = TestClient(deps.app)

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def pair(self, name="a", text="台詞"):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix(".wav").write_bytes(wav_bytes(1))
        path.with_suffix(".txt").write_text(text, encoding="utf-8")

    def freeze(self, record, edits=None):
        target = self.root / "frozen"
        target.mkdir(exist_ok=True)
        return freeze_rows(record["datasetId"], edits or record["rows"], target)

    def test_recursive_pairs_ignore_readme_and_keep_originals_and_frozen_audio(self):
        self.pair("one/voice", "一番")
        self.pair("two/voice", "二番")
        (self.source / "README.txt").write_text("学習本文にしない")
        (self.source / "other.txt").write_text("対応なし")
        before = {path.relative_to(self.source): digest(path) for path in self.source.rglob("*") if path.is_file()}
        response = self.client.post("/api/lora/inputs/folder", json={"path": str(self.source)})
        self.assertEqual(response.status_code, 200)
        record = response.json()
        self.assertEqual(record["folderName"], "source")
        self.assertEqual(record["ignoredTextCount"], 2)
        self.assertEqual([r["relativePath"] for r in record["rows"]], ["one/voice.wav", "two/voice.wav"])
        self.assertEqual([r["text"] for r in record["rows"]], ["一番", "二番"])
        self.assertEqual([r["caption"] for r in record["rows"]], ["", ""])
        self.assertEqual(before, {path.relative_to(self.source): digest(path) for path in self.source.rglob("*") if path.is_file()})
        (self.source / "one/voice.wav").write_bytes(wav_bytes(2))
        preview = self.client.get(record["rows"][0]["audioUrl"])
        self.assertEqual(preview.content, wav_bytes(1))
        self.assertEqual(preview.headers["cache-control"], "no-store")
        rows = self.freeze(record)
        self.assertEqual((self.root / "frozen" / rows[0]["wav"]).read_bytes(), wav_bytes(1))
        self.assertEqual(rows[0]["text"], "一番")

    def test_missing_and_invalid_utf8_text_remain_editable_wav_rows(self):
        (self.source / "missing.wav").write_bytes(wav_bytes(1))
        self.pair("invalid")
        (self.source / "invalid.txt").write_bytes(b"\xff\xfe")
        record = folders.stage_folder(str(self.source))
        self.assertEqual(len(record["rows"]), 2)
        self.assertTrue(all(row["issues"] and not row["blocked"] for row in record["rows"]))
        self.assertTrue(all(row["text"] == "" for row in record["rows"]))
        edits = [{**row, "text": "修正本文"} for row in record["rows"]]
        self.assertEqual(len(self.freeze(record, edits)), 2)

    def test_case_and_unicode_ambiguity_keeps_rows_but_cannot_be_overridden(self):
        self.pair("good1")
        self.pair("good2")
        (self.source / "VOICE.wav").write_bytes(wav_bytes(1))
        (self.source / "voice.txt").write_text("大小文字が違う")
        record = folders.stage_folder(str(self.source))
        blocked = [r for r in record["rows"] if r["blocked"]]
        self.assertEqual(len(blocked), 1)
        self.assertTrue(all(row["wavName"] and row["issues"] for row in blocked))
        edits = [{**r, "text": "強制修正", "blocked": False} for r in record["rows"]]
        with self.assertRaises(HTTPException) as caught:
            self.freeze(record, edits)
        self.assertEqual(caught.exception.status_code, 422)
        edits = [{**r, "excluded": r["blocked"]} for r in record["rows"]]
        self.assertEqual(len(self.freeze(record, edits)), 2)
        self.assertEqual(folders.canonical_key(Path("é.wav")), folders.canonical_key(Path("e\u0301.txt")))
        group = folders.grouped_files(self.source, [self.source / name for name in ("VOICE.wav", "voice.WAV", "voice.txt", "VOICE.TXT")])
        self.assertEqual(len(group["voice"]["wav"]), 2)
        self.assertEqual(len(group["voice"]["txt"]), 2)

    def test_multiple_wav_and_text_candidates_are_all_retained_and_blocked(self):
        self.pair("first")
        self.pair("second")
        directory = self.root / "staged"
        directory.mkdir()
        group = {"ambiguous": {"wav": [self.source / "first.wav", self.source / "second.wav"],
                                "txt": [self.source / "first.txt", self.source / "second.txt"]}}
        rows, ignored = folders._folder_rows(self.source, group, directory, "a" * 32)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["blocked"] for row in rows))
        self.assertTrue(all(len(row["textCandidates"]) == 2 for row in rows))
        self.assertEqual(ignored, 0)

    def test_static_symlinks_inside_and_outside_are_rejected_without_copy(self):
        outside = self.root / "outside.wav"
        outside.write_bytes(wav_bytes(2))
        for target in (outside, self.source / "regular.wav"):
            (self.source / "regular.wav").write_bytes(wav_bytes(1))
            link = self.source / "linked.wav"
            link.symlink_to(target)
            with self.assertRaises(HTTPException) as caught:
                folders.stage_folder(str(self.source))
            self.assertEqual(caught.exception.status_code, 422)
            link.unlink()
        self.assertEqual(outside.read_bytes(), wav_bytes(2))
        self.assertFalse((self.assets / "lora/inputs").exists())

    def test_scan_then_symlink_replacement_keeps_original_identity_and_rejects(self):
        self.pair()
        outside = self.root / "outside.wav"
        outside.write_bytes(wav_bytes(2))
        target_inside = self.source / "target.wav"
        original_scan = folders.scan_folder
        for target in (outside, target_inside):
            target_inside.write_bytes(wav_bytes(3))
            original = self.source / "a.wav"
            original.unlink()
            original.write_bytes(wav_bytes(1))
            def swapped(source):
                result = original_scan(source)
                original.unlink()
                original.symlink_to(target)
                return result
            with patch.object(folders, "scan_folder", side_effect=swapped):
                with self.assertRaises(HTTPException) as caught:
                    folders.stage_folder(str(self.source))
            self.assertEqual(caught.exception.status_code, 422)
            self.assertEqual(list((self.assets / "lora/inputs").iterdir()), [])

    def test_selected_folder_replaced_after_scan_is_rejected(self):
        self.pair()
        original_scan = folders.scan_folder
        moved = self.root / "original"
        other = self.root / "other"
        other.mkdir()
        (other / "a.wav").write_bytes(wav_bytes(2))
        def swapped(source):
            result = original_scan(source)
            self.source.rename(moved)
            self.source.symlink_to(other, target_is_directory=True)
            return result
        with patch.object(folders, "scan_folder", side_effect=swapped):
            with self.assertRaises(HTTPException) as caught:
                folders.stage_folder(str(self.source))
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual((moved / "a.wav").read_bytes(), wav_bytes(1))
        self.assertEqual((other / "a.wav").read_bytes(), wav_bytes(2))
        self.assertFalse((self.assets / "lora/inputs").exists())

    def test_limits_and_hundred_pairs_with_originals_unchanged(self):
        for index in range(100):
            self.pair(f"pair{index:03d}")
        record = folders.stage_folder(str(self.source))
        self.assertEqual(len(record["rows"]), 100)
        self.assertEqual(record["limits"]["maxFiles"], 500)
        for constant, limit, status in (("MAX_FOLDER_FILES", 1, 413), ("MAX_FOLDER_ENTRIES", 1, 413),
                                        ("MAX_FILE_BYTES", 1, 422), ("MAX_TOTAL_BYTES", 1, 413)):
            with patch.object(folders, constant, limit):
                with self.assertRaises(HTTPException) as caught:
                    folders.stage_folder(str(self.source))
            self.assertEqual(caught.exception.status_code, status)
        self.assertEqual(len(list((self.assets / "lora/inputs").iterdir())), 1)
        self.assertEqual((self.source / "pair000.wav").read_bytes(), wav_bytes(1))

    def test_audio_preview_uuid_hash_path_and_symlink_guards(self):
        self.pair()
        record = folders.stage_folder(str(self.source))
        row = record["rows"][0]
        url = row["audioUrl"]
        self.assertEqual(self.client.get(url.replace(row["id"], "bad")).status_code, 422)
        self.assertEqual(self.client.get(url.replace(record["datasetId"], "bad")).status_code, 422)
        self.assertEqual(self.client.get(url.replace(row["id"], "0" * 32)).status_code, 404)
        staged = input_audio_path(record["datasetId"], row["id"])
        staged.write_bytes(wav_bytes(2))
        self.assertEqual(self.client.get(url).status_code, 409)
        staged.unlink()
        staged.symlink_to(self.source / "a.wav")
        self.assertEqual(self.client.get(url).status_code, 409)
        row["source"]["wav"]["file"] = "../outside.wav"
        write_json(owned_path("inputs", record["datasetId"]) / "record.json", record)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_invalid_folder_and_request_shape_are_rejected(self):
        for path in ("relative", str(self.source / "absent")):
            response = self.client.post("/api/lora/inputs/folder", json={"path": path})
            self.assertEqual(response.status_code, 422)
        response = self.client.post("/api/lora/inputs/folder", json={"path": str(self.source), "extra": 1})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post("/api/lora/inputs/folder", json={"path": str(self.source)}).status_code, 422)

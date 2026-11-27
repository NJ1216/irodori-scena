import scena_test_isolation  # noqa: F401
import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server import app as _app  # noqa: F401
from server.modules import cast_exchange, constants, project_repository


def wav_bytes(marker: bytes = b"voice") -> bytes:
    return b"RIFF" + (36 + len(marker)).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little") + b"\x01\x00\x01\x00\x80\xbb\x00\x00\x00w\x01\x00\x02\x00\x10\x00data" + len(marker).to_bytes(4, "little") + marker


class CastExchangeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.media = self.root / "global-media"
        self.media.mkdir()
        self.reference = self.media / "characters" / "cast-a" / "reference.wav"
        self.reference.parent.mkdir(parents=True)
        self.reference.write_bytes(wav_bytes())
        self.character = {
            "id": "cast-a", "name": "彩", "profile": "主人公", "profileDetails": {"firstPerson": ["私"]},
            "voiceKeywords": "明るい声", "referenceFile": str(self.reference), "referenceAudioUrl": "/global-media/characters/cast-a/reference.wav", "createdAt": 123,
        }
        self.patches = [
            patch.object(constants, "GLOBAL_MEDIA_ROOT", self.media),
            patch.object(project_repository, "read_project", return_value={"characters": [self.character]}),
            patch.object(project_repository, "read_global_characters", return_value=[]),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        with cast_exchange._sessions_lock:
            sessions = list(cast_exchange._sessions.values())
            cast_exchange._sessions.clear()
        for session in sessions:
            import shutil
            shutil.rmtree(session["root"], ignore_errors=True)
        self.temporary.cleanup()

    def export_file(self) -> Path:
        output = self.root / "exports"
        output.mkdir(exist_ok=True)
        result = cast_exchange.export_casts(cast_exchange.CastExportRequest(cast_ids=["cast-a"], destination_dir=str(output)))
        self.assertEqual(result["results"][0]["status"], "exported")
        return output / "彩.scenacast"

    def test_export_is_deflated_and_restores_wav_byte_for_byte(self):
        output = self.export_file()
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(archive.getinfo("reference.wav").compress_type, zipfile.ZIP_DEFLATED)
            self.assertEqual(archive.read("reference.wav"), self.reference.read_bytes())
            manifest = json.loads(archive.read("manifest.json"))
        self.assertEqual(manifest["format"], cast_exchange.FORMAT)
        self.assertEqual(manifest["assets"]["reference.wav"]["sha256"], hashlib.sha256(self.reference.read_bytes()).hexdigest())
        self.assertNotIn("referenceFile", manifest)
        self.assertNotIn("scope", manifest)

    def test_export_reports_all_collisions_before_writing(self):
        output = self.root / "exports"
        output.mkdir()
        existing = output / "彩.scenacast"
        existing.write_bytes(b"old")
        with self.assertRaises(HTTPException) as raised:
            cast_exchange.export_casts(cast_exchange.CastExportRequest(cast_ids=["cast-a"], destination_dir=str(output)))
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(existing.read_bytes(), b"old")

    def test_prepare_rejects_duplicate_and_traversal_members_but_keeps_valid_sibling(self):
        good = self.export_file()
        bad = self.root / "bad.scenacast"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("../reference.wav", wav_bytes())
            archive.writestr("manifest.json", "{}")
        result = cast_exchange.prepare_cast_import(cast_exchange.CastImportPrepareRequest(paths=[str(bad), str(good)]))
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["items"][0]["status"], "new")

    def test_prepare_rejects_hash_mismatch(self):
        source = self.export_file()
        broken = self.root / "broken.scenacast"
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(broken, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for info in archive.infolist():
                output.writestr(info.filename, b"changed" if info.filename == "reference.wav" else archive.read(info.filename))
        result = cast_exchange.prepare_cast_import(cast_exchange.CastImportPrepareRequest(paths=[str(broken)]))
        self.assertEqual(result["items"], [])
        self.assertIn("ハッシュ", result["errors"][0]["error"])

    def test_commit_new_cast_remaps_known_relations_and_drops_missing(self):
        other = dict(self.character, id="cast-b", name="蓮", profileDetails={"castRelations": {"cast-a": {"note": "友人"}, "missing": {"note": "不明"}}})
        other_reference = self.media / "characters" / "cast-b" / "reference.wav"
        other_reference.parent.mkdir(parents=True)
        other_reference.write_bytes(wav_bytes(b"other"))
        other["referenceFile"] = str(other_reference)
        with patch.object(project_repository, "read_project", return_value={"characters": [self.character, other]}):
            output = self.root / "pair"
            output.mkdir()
            cast_exchange.export_casts(cast_exchange.CastExportRequest(cast_ids=["cast-a", "cast-b"], destination_dir=str(output)))
        written = []
        with patch.object(project_repository, "write_global_characters", side_effect=lambda value: written.append(value)):
            prepared = cast_exchange.prepare_cast_import(cast_exchange.CastImportPrepareRequest(paths=[str(output / "彩.scenacast"), str(output / "蓮.scenacast")]))
            result = cast_exchange.commit_cast_import(cast_exchange.CastImportCommitRequest(session_id=prepared["sessionId"]))
        self.assertEqual(len(result["applied"]), 2)
        relations = next(item for item in written[-1] if item["id"] == "cast-b")["profileDetails"]["castRelations"]
        self.assertEqual(set(relations), {"cast-a"})


if __name__ == "__main__":
    unittest.main()

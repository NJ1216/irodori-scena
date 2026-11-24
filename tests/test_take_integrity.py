from __future__ import annotations

import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.app import app as _registered_app  # noqa: F401
from server.modules.script_routes import create_line_take
from server.modules.take_integrity import repair_project_take_wavs, validate_take_wav


def write_wav(path: Path, frames: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\0\0" * frames)


class TakeIntegrityTests(unittest.TestCase):
    def test_successful_generation_promotes_only_used_global_manual_entry(self) -> None:
        with TemporaryDirectory() as directory:
            root, media_root = Path(directory), Path(directory) / "media"
            reference = root / "reference.wav"
            write_wav(reference)
            project = {"settings": {"seed": 7, "speechRate": 1.2}, "characters": [{"id": "cast", "referenceFile": str(reference)}], "scenes": [{"lines": []}], "pronunciationDictionary": []}
            line = {"id": "line", "characterId": "cast", "text": "東京", "stageDirection": ""}
            project["scenes"][0]["lines"].append(line)
            global_entries = [
                {"id": "used", "term": "東京", "reading": "とうきょう", "source": "manual"},
                {"id": "unused", "term": "大阪", "reading": "おおさか", "source": "manual"},
            ]

            def render(**kwargs):
                write_wav(kwargs["output"])

            with (
                patch("server.modules.constants.MEDIA_ROOT", media_root),
                patch("server.modules.inference.run_irodori", side_effect=render),
                patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=global_entries),
            ):
                create_line_take(project, line, "fast", take_id="take")
            self.assertEqual([entry["term"] for entry in project["pronunciationDictionary"]], ["東京"])
            self.assertEqual(project["pronunciationDictionary"][0]["projectScopeOrigin"], "script-auto")

    def test_missing_take_restoration_uses_saved_text_seed_settings_and_id(self) -> None:
        with TemporaryDirectory() as directory:
            root, media_root = Path(directory), Path(directory) / "media"
            reference = root / "reference.wav"
            write_wav(reference)
            project = {
                "settings": {"seed": 1, "speechRate": 1.2, "steps": 16},
                "ttsSelection": {"engine": {"commit": "engine"}, "model": {"revision": "model"}, "codecRevision": "codec"},
                "characters": [{"id": "cast", "referenceFile": str(reference)}],
                "scenes": [{"lines": []}],
            }
            line = {"id": "line", "characterId": "cast", "text": "changed", "stageDirection": "changed"}
            project["scenes"][0]["lines"].append(line)
            saved = {
                "id": "same-take", "seed": 99, "quality": "quality", "renderedText": "保存済み本文",
                "stageDirection": "保存済み演出", "settings": {"speechRate": 0.9, "steps": 40, "textCfg": 2.0, "voiceCfg": 4.0, "captionCfg": 2.5},
                "ttsConfiguration": {"engineCommit": "engine", "modelRevision": "model", "codecRevision": "codec"},
                "createdAt": 123,
            }

            def render(**kwargs):
                self.assertEqual(kwargs["text"], "保存済み本文")
                self.assertEqual(kwargs["seed"], 99)
                self.assertEqual(kwargs["caption"], "保存済み演出")
                self.assertEqual(kwargs["generation_settings"]["steps"], 40)
                write_wav(kwargs["output"])

            with (
                patch("server.modules.constants.MEDIA_ROOT", media_root),
                patch("server.modules.inference.run_irodori", side_effect=render),
                patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]),
                patch("server.modules.inference.last_inference_execution", return_value={}),
            ):
                take = create_line_take(project, line, "quality", take_id="same-take", restore_take=saved)
            self.assertEqual(take["id"], "same-take")
            self.assertEqual(take["createdAt"], 123)

    def test_repairs_only_broken_managed_takes_and_selects_a_valid_sibling(self) -> None:
        with TemporaryDirectory() as directory:
            media_root = Path(directory) / "media"
            valid = media_root / "takes" / "line-1" / "valid.wav"
            broken = media_root / "takes" / "line-1" / "broken.wav"
            partial = media_root / "takes" / "line-2" / ".partial-take-render.wav"
            orphan = media_root / "takes" / "deleted-line" / "orphan.wav"
            write_wav(valid)
            write_wav(orphan)
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_bytes(b"RIFF incomplete")
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"partial")
            project = {"scenes": [{"lines": [{
                "id": "line-1", "selectedTakeId": "broken",
                "takes": [
                    {"id": "valid", "audioUrl": "/media/takes/line-1/valid.wav"},
                    {"id": "broken", "audioUrl": "/media/takes/line-1/broken.wav"},
                    {"id": "missing", "audioUrl": "/media/takes/line-1/missing.wav"},
                    {"id": "external", "audioUrl": "https://example.com/take.wav"},
                ],
            }]}]}

            with patch("server.modules.constants.MEDIA_ROOT", media_root):
                removed = repair_project_take_wavs(project)

            line = project["scenes"][0]["lines"][0]
            self.assertEqual(removed, 2)
            self.assertEqual([take["id"] for take in line["takes"]], ["valid", "external"])
            self.assertEqual(line["selectedTakeId"], "external")
            self.assertFalse(broken.exists())
            self.assertFalse(partial.exists())
            self.assertFalse(orphan.exists())
            self.assertFalse(orphan.parent.exists())
            self.assertTrue(valid.exists())

    def test_detects_pcm_data_truncated_after_a_valid_header(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "truncated.wav"
            write_wav(path)
            path.write_bytes(path.read_bytes()[:-2])
            with self.assertRaisesRegex(ValueError, "Invalid take WAV"):
                validate_take_wav(path)

    def test_invalid_render_never_replaces_the_previous_take(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media_root = root / "media"
            reference = root / "reference.wav"
            output = media_root / "takes" / "line" / "take.wav"
            write_wav(reference)
            write_wav(output, frames=4)
            previous = output.read_bytes()
            project = {
                "settings": {"seed": 7, "speechRate": 1.2},
                "characters": [{"id": "cast", "referenceFile": str(reference)}],
                "scenes": [{"lines": []}],
            }
            line = {"id": "line", "characterId": "cast", "text": "台詞", "stageDirection": ""}
            project["scenes"][0]["lines"].append(line)

            def write_broken(**kwargs):
                kwargs["output"].write_bytes(b"RIFF incomplete")

            with (
                patch("server.modules.constants.MEDIA_ROOT", media_root),
                patch("server.modules.inference.run_irodori", side_effect=write_broken),
                self.assertRaisesRegex(ValueError, "Invalid take WAV"),
            ):
                create_line_take(project, line, "fast", take_id="take")

            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(list(output.parent.glob(".partial-*.wav")), [])


if __name__ == "__main__":
    unittest.main()

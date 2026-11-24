from __future__ import annotations

import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.modules.export_service import line_render_signature
from server.modules.script_routes import create_line_take


def write_silence(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\0\0" * 24)


class LineCfgOverrideTests(unittest.TestCase):
    def test_meanflow_ignores_but_preserves_project_and_line_cfg(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            write_silence(reference)
            project = {
                "settings": {"seed": 7, "speechRate": 1.2, "steps": 40, "quality": "quality", "textCfg": 8.0, "voiceCfg": 9.0, "captionCfg": 7.0},
                "ttsSelection": {"engine": {"commit": "89f9d8fbd4d51ea019867ee1197725ede1df13c5"}, "model": {"repo": "Aratako/Irodori-TTS-v4.1-Small-MF", "revision": "ccc78f5d480b6e51b69b2d5042a14c4da04fea6e"}},
                "characters": [{"id": "cast", "referenceFile": str(reference)}],
                "scenes": [{"lines": []}],
            }
            line = {"id": "line", "characterId": "cast", "text": "台詞", "textCfg": 1.0}
            project["scenes"][0]["lines"].append(line)
            captured = {}

            def synthesize(**kwargs):
                captured.update(kwargs["generation_settings"])
                write_silence(kwargs["output"])

            with patch("server.modules.constants.MEDIA_ROOT", root / "media"), patch("server.modules.inference.run_irodori", side_effect=synthesize):
                take = create_line_take(project, line, "quality", take_id="take")

            self.assertEqual(captured["steps"], 4)
            self.assertTrue({"textCfg", "voiceCfg", "captionCfg"}.isdisjoint(captured))
            self.assertEqual(take["settings"], {"speechRate": 1.2, "steps": 4})
            changed = {**project, "settings": {**project["settings"], "textCfg": 2.0, "quality": "turbo", "steps": 8}}
            self.assertEqual(line_render_signature(project, line), line_render_signature(changed, {**line, "textCfg": 6.0}))
            self.assertEqual(project["settings"]["textCfg"], 8.0)

    def test_fixed_seed_precedes_shared_and_random_seed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            write_silence(reference)
            project = {
                "settings": {"seed": 7, "speechRate": 1.2, "steps": 16},
                "characters": [{"id": "cast", "referenceFile": str(reference)}],
                "scenes": [{"lines": []}],
            }
            line = {"id": "line", "characterId": "cast", "text": "台詞", "fixedSeed": 91, "manualSeed": 92}
            project["scenes"][0]["lines"].append(line)
            captured: list[int] = []

            def synthesize(**kwargs):
                captured.append(kwargs["seed"])
                write_silence(kwargs["output"])

            with (
                patch("server.modules.constants.MEDIA_ROOT", root / "media"),
                patch("server.modules.inference.run_irodori", side_effect=synthesize),
                patch("server.modules.script_routes.secrets.randbelow", return_value=123),
            ):
                explicit = create_line_take(project, line, "fast", take_id="explicit", seed_override=93)
                manual = create_line_take(project, line, "fast", take_id="manual")
                line.pop("manualSeed")
                fixed = create_line_take(project, line, "fast", take_id="fixed")
                line.pop("fixedSeed")
                shared = create_line_take(project, line, "fast", take_id="shared")
                project["settings"]["seed"] = 0
                random = create_line_take(project, line, "fast", take_id="random")

            self.assertEqual(captured, [93, 92, 91, 7, 123])
            self.assertEqual(
                [explicit["seed"], manual["seed"], fixed["seed"], shared["seed"], random["seed"]], captured
            )

    def test_manual_seed_precedes_fixed_seed(self) -> None:
        project = {"settings": {"seed": 7}}
        line = {"manualSeed": 92, "fixedSeed": 91}
        self.assertNotEqual(line_render_signature(project, line), line_render_signature(project, {**line, "manualSeed": 93}))
        self.assertEqual(line_render_signature(project, line), line_render_signature({"settings": {"seed": 8}}, line))

    def test_generation_uses_independent_line_overrides_and_records_effective_values(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            write_silence(reference)
            project = {
                "settings": {"seed": 7, "speechRate": 1.2, "steps": 16, "textCfg": 3.0, "voiceCfg": 5.0, "captionCfg": 3.0},
                "characters": [{"id": "cast", "referenceFile": str(reference)}],
                "scenes": [{"lines": []}],
            }
            line = {"id": "line", "characterId": "cast", "text": "台詞", "stageDirection": "静かに", "textCfg": 4.2, "captionCfg": 6.4}
            project["scenes"][0]["lines"].append(line)
            captured = {}

            def synthesize(**kwargs):
                captured.update(kwargs["generation_settings"])
                write_silence(kwargs["output"])

            with (
                patch("server.modules.constants.MEDIA_ROOT", root / "media"),
                patch("server.modules.inference.run_irodori", side_effect=synthesize),
            ):
                take = create_line_take(project, line, "fast", take_id="take")

            self.assertEqual((captured["textCfg"], captured["voiceCfg"], captured["captionCfg"]), (4.2, 5.0, 6.4))
            self.assertEqual(take["settings"], {"speechRate": 1.2, "steps": 16, "textCfg": 4.2, "voiceCfg": 5.0, "captionCfg": 6.4})

    def test_render_signature_uses_effective_cfg_values(self) -> None:
        project = {"settings": {"textCfg": 3.0, "voiceCfg": 5.0, "captionCfg": 3.0}}
        inherited = {"id": "line", "text": "台詞", "characterId": "cast"}
        overridden = {**inherited, "voiceCfg": 6.1}
        self.assertNotEqual(line_render_signature(project, inherited), line_render_signature(project, overridden))
        equivalent_project = {"settings": {"textCfg": 3.0, "voiceCfg": 6.1, "captionCfg": 3.0}}
        self.assertEqual(line_render_signature(project, overridden), line_render_signature(equivalent_project, inherited))

    def test_render_signature_uses_fixed_seed_before_shared_seed(self) -> None:
        project = {"settings": {"seed": 7}}
        line = {"id": "line", "fixedSeed": 91}
        self.assertNotEqual(line_render_signature(project, line), line_render_signature(project, {**line, "fixedSeed": 92}))
        self.assertEqual(line_render_signature(project, line), line_render_signature({"settings": {"seed": 8}}, line))


if __name__ == "__main__":
    unittest.main()

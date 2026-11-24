from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from server.app import app as _registered_app  # noqa: F401
from server.modules import export_service, runtime_state


class ExportTakeSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.project = {
            "settings": {}, "characters": [{"id": "cast"}],
            "scenes": [{"id": "scene", "lines": [{"id": "line", "text": "台詞", "characterId": "cast", "takes": [], "selectedTakeId": None}]}],
        }
        self.line = self.project["scenes"][0]["lines"][0]
        self.outputs = []
        self.enterContext(patch("server.modules.constants.MEDIA_ROOT", self.root))
        self.enterContext(patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]))
        self.enterContext(patch("server.modules.project_repository.read_project", side_effect=lambda: deepcopy(self.project)))
        self.write = self.enterContext(patch("server.modules.project_repository.write_project"))

    def missing_take(self):
        self.line.update(takes=[{"id": "missing", "audioUrl": "/media/missing.wav", "seed": 7}], selectedTakeId="missing")

    def generate(self, edit):
        def render(*_args, take_id=None, **_kwargs):
            take_id = take_id or f"new-{len(self.outputs)}"
            output = self.root / f"{take_id}.wav"
            output.write_bytes(b"stub synthesis")
            self.outputs.append(output)
            if len(self.outputs) == 1:
                edit()
            return {"id": take_id, "audioUrl": f"/media/{output.name}"}
        with patch("server.modules.script_routes.create_line_take", side_effect=render):
            return export_service.ensure_export_take("line", "fast", should_cancel=lambda: False)

    def select_existing(self):
        (self.root / "chosen.wav").write_bytes(b"user selected audio")
        self.line["takes"].append({"id": "chosen", "audioUrl": "/media/chosen.wav"})
        self.line["selectedTakeId"] = "chosen"

    def test_deleted_restoration_target_is_not_saved_as_a_dangling_selection(self) -> None:
        self.missing_take()
        _, _, line, generated = self.generate(lambda: self.line.update(takes=[], selectedTakeId=None))
        self.assertTrue(generated)
        self.assertEqual(line["selectedTakeId"], "new-1")
        self.assertEqual([take["id"] for take in line["takes"]], ["new-1"])
        self.assertEqual(len(self.outputs), 2)
        self.assertFalse(self.outputs[0].exists())
        self.assertTrue(self.outputs[1].exists())
        self.write.assert_called_once()

    def test_user_selection_during_generation_wins_and_reuses_existing_audio(self) -> None:
        _, _, line, generated = self.generate(self.select_existing)
        self.assertFalse(generated)
        self.assertEqual(line["selectedTakeId"], "chosen")
        self.assertFalse(self.outputs[0].exists())
        self.assertTrue((self.root / "chosen.wav").exists())
        self.write.assert_not_called()

    def test_user_selection_during_restoration_wins(self) -> None:
        self.missing_take()
        _, _, line, generated = self.generate(self.select_existing)
        self.assertFalse(generated)
        self.assertEqual(line["selectedTakeId"], "chosen")
        self.assertFalse(self.outputs[0].exists())
        self.write.assert_not_called()

    def test_unchanged_restoration_replaces_the_same_record(self) -> None:
        self.missing_take()
        _, _, line, generated = self.generate(lambda: None)
        self.assertTrue(generated)
        self.assertEqual(line["selectedTakeId"], "missing")
        self.assertEqual([take["id"] for take in line["takes"]], ["missing"])
        self.assertTrue(self.outputs[0].exists())
        self.write.assert_called_once()

    def test_bundle_uses_latest_selection_even_when_no_generated_take_is_committed(self) -> None:
        job = {"id": "selection", "mode": "bundle", "status": "preparing", "request": {"formats": ["wav"]}}
        stale_audio = self.root / "discarded.wav"

        def render(*_args, **_kwargs):
            stale_audio.write_bytes(b"obsolete generation")
            self.select_existing()
            return {"id": "discarded", "audioUrl": "/media/discarded.wav"}

        def bundle(_job_id, project, _request):
            line = project["scenes"][0]["lines"][0]
            self.assertEqual(line["selectedTakeId"], "chosen")
            self.assertTrue(export_service.selected_take_is_available(line))
            return str(self.root / "export"), 1, []

        with (
            patch.object(runtime_state, "EXPORT_JOBS", {job["id"]: job}),
            patch("server.modules.script_routes.create_line_take", side_effect=render),
            patch("server.modules.export_bundle.export_bundle", side_effect=bundle) as export,
        ):
            export_service.run_export_job(job["id"])
        self.assertEqual(job["status"], "completed", job.get("error"))
        self.assertEqual(job["generatedLines"], 0)
        self.assertEqual(job["lineUpdates"][0]["line"]["selectedTakeId"], "chosen")
        export.assert_called_once()
        self.assertFalse(stale_audio.exists())


if __name__ == "__main__":
    unittest.main()

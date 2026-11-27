from __future__ import annotations

import scena_test_isolation  # noqa: F401
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from server.app import GenerateLineRequest
from server.modules import export_service, script_routes
from server.modules.line_synthesis_inputs import line_speech_timing, line_spoken_text


def project_fixture():
    return {
        "id": "project", "settings": {"speechRate": 1, "seed": 7},
        "characters": [{"id": "cast", "referenceFile": "/reference.wav", "referenceVersion": 1}],
        "pronunciationDictionary": [{"id": "word", "source": "manual", "term": "日本", "reading": "にほん"}],
        "scenes": [{"id": "scene", "lines": [{"id": "line", "characterId": "cast", "text": "日本", "takes": [], "selectedTakeId": None}]}],
    }


def first_line(project):
    return project["scenes"][0]["lines"][0]


class RenderInputIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]))

    def test_export_retries_changed_duration_or_inline_reading_and_discards_stale_audio(self) -> None:
        for change in [{"targetDurationSeconds": 5}, {"pronunciations": [{"id": "span", "text": "日本", "start": 0, "end": 2, "reading": "にっぽん"}]}]:
            with self.subTest(change=change), TemporaryDirectory() as directory:
                project = project_fixture()
                outputs = []
                def render(snapshot, line, *_args, **_kwargs):
                    text, _ = line_spoken_text(snapshot, line)
                    _, duration = line_speech_timing(snapshot, line)
                    path = Path(directory) / f"take-{len(outputs)}.wav"
                    path.write_bytes(b"stub synthesis")
                    outputs.append(path)
                    first_line(project).update(change)
                    return {"id": path.stem, "audioUrl": f"/media/{path.name}", "renderedText": text, "targetDurationSeconds": duration}

                with (
                    patch("server.modules.constants.MEDIA_ROOT", Path(directory)),
                    patch("server.modules.project_repository.read_project", side_effect=lambda: deepcopy(project)),
                    patch("server.modules.project_repository.write_project") as write,
                    patch.object(script_routes, "create_line_take", side_effect=render),
                ):
                    saved, _, line, generated = export_service.ensure_export_take("line", "fast", should_cancel=lambda: False)
                self.assertTrue(generated)
                write.assert_called_once()
                self.assertEqual(len(outputs), 2)
                self.assertFalse(outputs[0].exists())
                self.assertTrue(outputs[1].exists())
                self.assertEqual(line["selectedTakeId"], "take-1")
                self.assertEqual(line["takes"][-1]["renderedText"], line_spoken_text(saved, line)[0])
                self.assertEqual(line["takes"][-1]["targetDurationSeconds"], line_speech_timing(saved, line)[1])

    def test_signature_tracks_dictionary_reference_and_linked_cue_inputs(self) -> None:
        def dictionary(project):
            project["pronunciationDictionary"][0]["reading"] = "にっぽん"
        def reference(project):
            project["characters"][0]["referenceVersion"] += 1
        def cue(project):
            first_line(project)["cueId"] = "cue"
            project["scenes"][0]["lines"].append({"id": "other", "cueId": "cue", "takes": [{"id": "other-take", "durationSeconds": 3, "createdAt": 1}], "selectedTakeId": "other-take"})
        for change in [dictionary, reference, cue]:
            with self.subTest(change=change.__name__):
                before = project_fixture()
                after = deepcopy(before)
                change(after)
                self.assertNotEqual(export_service.line_render_signature(before, first_line(before)), export_service.line_render_signature(after, first_line(after)))

    def test_irrelevant_edits_and_equivalent_effective_inputs_do_not_change_signature(self) -> None:
        before = project_fixture()
        after = deepcopy(before)
        after["title"] = "別の題名"
        first_line(after)["gapSeconds"] = 2
        after["pronunciationDictionary"].append({"id": "unused", "source": "manual", "term": "大阪", "reading": "おおさか"})
        first_line(after)["pronunciations"] = [{"id": "span", "text": "日本", "start": 0, "end": 2, "reading": "にほん"}]
        self.assertEqual(export_service.line_render_signature(before, first_line(before)), export_service.line_render_signature(after, first_line(after)))

    def test_manual_generation_rejects_input_changed_during_synthesis(self) -> None:
        before = project_fixture()
        after = deepcopy(before)
        first_line(after)["targetDurationSeconds"] = 5
        take = {"id": "generated", "audioUrl": "/media/generated.wav"}
        with (
            patch.object(export_service, "require_tts_available"),
            patch("server.modules.project_repository.read_project", side_effect=[before, after]),
            patch.object(script_routes, "create_line_take", return_value=take),
            patch("server.modules.take_commit.discard_generated_take") as discard,
            patch("server.modules.project_repository.write_project") as write,
            self.assertRaises(HTTPException) as raised,
        ):
            script_routes.generate_line("line", GenerateLineRequest(quality="fast"))
        self.assertEqual(raised.exception.detail["code"], "render_input_changed")
        discard.assert_called_once_with(take)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()

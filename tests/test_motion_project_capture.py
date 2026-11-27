from __future__ import annotations

import scena_test_isolation  # noqa: F401
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

from server.modules.motion_project_capture import GenerationEnvironment, capture_motion_project
from server.modules.motion_preparation import MotionPreparationService, PreparationDependencies
from server.modules.motion_preparation_artifacts import PreparationRequest, ProposedAudio, ProposedLab
from server.modules.project_models import StudioProjectModel


class MotionProjectCaptureTests(unittest.TestCase):
    def setUp(self):
        fixture = json.loads(Path("tests/fixtures/motion/minimal-common-bundle.json").read_text())
        self.project = StudioProjectModel.model_validate(fixture["project"])
        self.request = PreparationRequest("fixture-op", "fixture-project", "fixture-scene", "fixture-line")
        self.line = self.project.scenes[0].lines[0]
        self.environment = GenerationEnvironment("a" * 64, "fixture-engine", "fixture-model", "fixture-codec", "fixture-fp32", "fixture-effective-inputs-v1")

    def capture(self, **kwargs):
        return capture_motion_project(self.project, self.request, lambda _take: True, **kwargs)

    def test_existing_typed_project_selected_take_needs_no_runtime_or_reference_io(self):
        before = self.project.model_dump()
        snapshot = self.capture()
        self.assertFalse(snapshot.source.needs_generation)
        self.assertEqual(snapshot.source.selected_take_id, "fixture-take")
        self.assertEqual(snapshot.source.body, self.line.text)
        self.assertEqual(snapshot.source.gap_seconds, 0.25)
        encoded = json.dumps(snapshot.generation_inputs)
        for excluded in ("llmBaseUrl", "llmModel", "referenceFile", "privateExtra", "ttsSelection"):
            self.assertNotIn(excluded, encoded)
        self.assertEqual(self.project.model_dump(), before)

    def test_no_selection_requires_reviewed_generation_environment_and_keeps_old_take(self):
        self.line.selectedTakeId = None
        with self.assertRaises(ValueError):
            self.capture()
        snapshot = self.capture(generation_environment=self.environment)
        self.assertTrue(snapshot.source.needs_generation)
        self.assertEqual(snapshot.source.existing_take_ids, ("fixture-take",))
        self.assertEqual(snapshot.generation_inputs["environment"]["runtime_variant"], "fixture-fp32")
        self.assertIsNone(self.line.selectedTakeId)
        self.assertEqual(len(self.line.takes), 1)

    def test_input_identity_covers_generation_changes_without_project_revision_or_llm_fields(self):
        self.line.selectedTakeId = None
        before = self.capture(generation_environment=self.environment).inputs_identity
        self.project.revision += 1
        self.project.settings.llmModel = "unrelated"
        self.project.settings.llmBaseUrl = "http://unrelated.invalid"
        self.assertEqual(before, self.capture(generation_environment=self.environment).inputs_identity)
        for mutate in (
            lambda: setattr(self.line, "stageDirection", "changed"),
            lambda: setattr(self.project.settings, "seed", 123),
            lambda: setattr(self.project, "pronunciationDictionary", [{"term": "台詞", "reading": "せりふ"}]),
        ):
            mutate()
            after = self.capture(generation_environment=self.environment).inputs_identity
            self.assertNotEqual(before, after)
            before = after
        changed_environment = replace(self.environment, runtime_variant="fixture-bf16")
        self.assertNotEqual(before, self.capture(generation_environment=changed_environment).inputs_identity)

    def test_semantic_gap_keeps_subframe_precision_and_signed_zero_is_equivalent(self):
        from fractions import Fraction
        self.line.gapSeconds = 0.250001
        snapshot = self.capture()
        self.assertEqual(snapshot.source.gap_seconds, 0.250001)
        self.assertNotEqual(Fraction(str(snapshot.source.gap_seconds)), Fraction(1, 4))
        self.assertEqual(round(Fraction(str(snapshot.source.gap_seconds)) * 30), round(Fraction(1, 4) * 30))
        self.assertNotEqual(snapshot.source.gap_seconds, round(snapshot.source.gap_seconds, 2))

    def test_request_identity_and_duplicate_character_are_not_guessed(self):
        with self.assertRaises(ValueError):
            capture_motion_project(self.project, replace(self.request, project_id="other"), lambda _take: True)
        self.line.selectedTakeId = None
        self.project.characters.append(self.project.characters[0].model_copy(deep=True))
        with self.assertRaises(ValueError):
            self.capture(generation_environment=self.environment)

    def test_pronunciation_context_excludes_unknown_child_fields(self):
        from server.modules.project_models import PersistedPronunciation
        self.line.pronunciations = [PersistedPronunciation.model_validate({
            "id": "pron", "start": 0, "end": 1, "text": "こ", "reading": "こ", "privateExtra": "do not project",
        })]
        self.assertNotIn("privateExtra", json.dumps(self.capture().generation_inputs))

    def test_generation_reference_digest_and_environment_are_validated(self):
        self.line.selectedTakeId = None
        for environment in (replace(self.environment, reference_sha256="path-not-content"), replace(self.environment, engine_commit="")):
            with self.assertRaises(ValueError):
                self.capture(generation_environment=environment)

    def test_typed_capture_connects_to_preparation_service_with_immutable_fixture_media(self):
        from io import BytesIO
        import wave
        buffer = BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            writer.writeframes(b"\x01\x00" * 160)
        audio = ProposedAudio("fixture-take", buffer.getvalue())
        dependencies = PreparationDependencies(
            lambda request: capture_motion_project(self.project, request, lambda _take: True),
            lambda snapshot, checkpoint: audio,
            lambda snapshot, checkpoint: self.fail("Selected fixture must not generate."),
            lambda audio, checkpoint: ProposedLab(b"0 100000 pau\n", hashlib.sha256(audio.wav).hexdigest(), "fixture-pau-v1"),
            lambda bundle, checkpoint: "fixture-receipt",
            lambda request, bundle, token, checkpoint: checkpoint(),
        )
        result = MotionPreparationService(dependencies).prepare(self.request, lambda: False)
        self.assertEqual(result.state, "prepared")
        self.assertEqual(result.bundle.dialogue_txt.decode(), self.line.text)
        self.assertEqual(self.line.selectedTakeId, "fixture-take")


if __name__ == "__main__":
    unittest.main()

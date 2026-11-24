from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import hashlib
import json
import threading
import unittest
import wave

from server.modules.motion_source import resolve_motion_source
from server.modules.motion_preparation import (
    MotionPreparationService, PreparationCancelled, PreparationDependencies,
    PreparationSourceChanged, PreparationStopped,
)
from server.modules.motion_preparation_artifacts import (
    PreparationRequest, PreparationSnapshot, ProposedAudio, ProposedLab,
)


def fixture_wav(sample=1):
    buffer = BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        writer.writeframes(sample.to_bytes(2, "little") * 160)
    return buffer.getvalue()


class MotionPreparationTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "id": "project", "revision": 1, "settings": {"lineGap": 0.25},
            "scenes": [{"id": "scene", "lines": [{
                "id": "line", "characterId": "cast", "text": "同じ本文🙂\n原文", "stageDirection": "quiet",
                "takes": [{"id": "old", "audioUrl": "/media/old.wav"}], "selectedTakeId": None,
            }]}],
        }
        self.line = self.project["scenes"][0]["lines"][0]
        self.calls = {name: 0 for name in ("load", "generate", "lab", "stage")}
        self.hooks = {}
        self.cancelled = False
        self.available = True
        self.audio = fixture_wav()
        self.lab = b"0 100000 a\n"
        self.request = PreparationRequest("op", "project", "scene", "line")
        self.service = MotionPreparationService(PreparationDependencies(
            self.capture, self.load, self.generate, self.derive, self.stage,
            lambda request, bundle, token, checkpoint: checkpoint(),
        ))

    def capture(self, request):
        source = resolve_motion_source(self.project, request.scene_id, request.line_id, lambda _take: self.available)
        inputs = {"stageDirection": self.line["stageDirection"]}
        token = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        return PreparationSnapshot(source, token, inputs)

    def call(self, name):
        self.calls[name] += 1
        if name in self.hooks:
            self.hooks[name]()

    def load(self, snapshot, checkpoint):
        self.call("load")
        return ProposedAudio(snapshot.source.selected_take_id, self.audio)

    def generate(self, snapshot, checkpoint):
        self.call("generate")
        self.assertTrue(snapshot.source.needs_generation)
        return ProposedAudio("new", self.audio)

    def derive(self, audio, checkpoint):
        self.call("lab")
        return ProposedLab(self.lab, hashlib.sha256(audio.wav).hexdigest(), "fixture-analyzer-v1")

    def stage(self, bundle, checkpoint):
        self.call("stage")
        self.assertEqual(bundle.dialogue_txt.decode(), bundle.snapshot.source.body)
        return "fixture-staging-receipt"

    def prepare(self):
        return self.service.prepare(self.request, lambda: self.cancelled)

    def select(self):
        self.line["selectedTakeId"] = "old"

    def test_unselected_old_take_uses_new_proposal_without_project_write(self):
        before = deepcopy(self.project)
        result = self.prepare()
        self.assertEqual(result.state, "prepared")
        self.assertEqual(result.audio.take_id, "new")
        self.assertEqual((result.bundle.frame_count, result.bundle.sample_rate), (160, 16000))
        self.assertEqual(result.bundle.snapshot.source.gap_seconds, 0.25)
        self.assertEqual(self.calls, {"load": 0, "generate": 1, "lab": 1, "stage": 1})
        self.assertEqual(self.project, before)

    def test_selected_take_and_missing_audio_paths(self):
        self.select()
        result = self.prepare()
        self.assertEqual(result.audio.take_id, "old")
        self.assertEqual(self.calls["generate"], 0)
        self.available = False
        request = replace(self.request, operation_id="missing-audio")
        result = self.service.prepare(request, lambda: False)
        self.assertEqual(result.audio.take_id, "new")
        self.assertEqual(self.line["selectedTakeId"], "old")

    def test_sequential_duplicate_returns_detached_same_result_without_extra_work(self):
        result = self.prepare()
        result.bundle.snapshot.source.selected_take_id  # not an adoption receipt
        result.snapshot.generation_inputs["stageDirection"] = "caller mutation"
        again = self.prepare()
        self.assertEqual(again.staging_receipt, result.staging_receipt)
        self.assertEqual(again.snapshot.generation_inputs["stageDirection"], "quiet")
        self.assertEqual(self.calls["generate"], 1)
        self.assertEqual(self.calls["stage"], 1)

    def test_concurrent_duplicate_performs_one_generation_and_staging(self):
        started, release = threading.Event(), threading.Event()
        def block():
            started.set()
            if not release.wait(2):
                raise RuntimeError("fixture synchronization timed out")
        self.hooks["generate"] = block
        results, errors = [], []
        def run():
            try:
                results.append(self.prepare())
            except Exception as error:
                errors.append(error)
        first = threading.Thread(target=run)
        second = threading.Thread(target=run)
        first.start()
        try:
            self.assertTrue(started.wait(2))
            second.start()
        finally:
            release.set()
            first.join(3)
            if second.ident is not None:
                second.join(3)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(self.calls["generate"], 1)
        self.assertEqual(self.calls["stage"], 1)

    def test_same_text_other_identity_and_operation_id_reuse_are_rejected(self):
        self.prepare()
        other = replace(self.request, line_id="other")
        with self.assertRaises(ValueError):
            self.service.prepare(other, lambda: False)
        wrong_project = replace(self.request, operation_id="new-op", project_id="other-project")
        with self.assertRaises(PreparationSourceChanged):
            self.service.prepare(wrong_project, lambda: False)
        self.assertEqual(self.calls["generate"], 1)

    def test_cancellation_boundaries_do_not_return_success_or_delete_generated_audio(self):
        for boundary in ("before", "generate", "lab", "stage"):
            with self.subTest(boundary=boundary):
                self.setUp()
                if boundary == "before":
                    self.cancelled = True
                else:
                    self.hooks[boundary] = lambda: setattr(self, "cancelled", True)
                with self.assertRaises(PreparationCancelled):
                    self.prepare()
                attempt = self.service.inspect("op")
                if boundary == "before":
                    self.assertIsNone(attempt)
                else:
                    self.assertEqual(attempt.state, "cancelled")
                    self.assertEqual(attempt.audio.wav, fixture_wav())
                    self.cancelled = False
                    with self.assertRaises(PreparationStopped):
                        self.prepare()
                self.assertIsNone(self.line["selectedTakeId"])

    def test_failed_audio_lab_and_storage_are_sticky_without_repeat_generation(self):
        for boundary in ("generate", "lab", "stage"):
            with self.subTest(boundary=boundary):
                self.setUp()
                def fail():
                    raise OSError("fixture failure")
                self.hooks[boundary] = fail
                with self.assertRaises(OSError):
                    self.prepare()
                attempt = self.service.inspect("op")
                self.assertEqual(attempt.state, "failed")
                self.assertEqual(attempt.staging_started, boundary == "stage")
                if boundary != "generate":
                    self.assertIsNotNone(attempt.audio)
                with self.assertRaises(PreparationStopped):
                    self.prepare()
                self.assertEqual(self.calls["generate"], 1)
                self.assertIsNone(self.line["selectedTakeId"])

    def test_changes_during_audio_lab_or_staging_do_not_return_stale_success(self):
        for boundary in ("generate", "lab", "stage"):
            for field, value in (("text", "changed"), ("selectedTakeId", "old"), ("gapSeconds", 0), ("stageDirection", "loud")):
                with self.subTest(boundary=boundary, field=field):
                    self.setUp()
                    self.hooks[boundary] = lambda: self.line.update({field: value})
                    with self.assertRaises(PreparationSourceChanged):
                        self.prepare()
                    self.assertEqual(self.service.inspect("op").state, "failed")
                    if boundary != "stage":
                        self.assertEqual(self.calls["stage"], 0)

    def test_selected_same_id_path_audio_overwrite_is_rejected_during_lab_and_retry(self):
        self.select()
        self.hooks["lab"] = lambda: setattr(self, "audio", fixture_wav(2))
        with self.assertRaises(PreparationSourceChanged):
            self.prepare()
        self.assertEqual(self.calls["stage"], 0)
        self.setUp()
        self.select()
        self.prepare()
        self.audio = fixture_wav(2)
        with self.assertRaises(PreparationSourceChanged):
            self.prepare()
        self.assertEqual(self.service.inspect("op").state, "failed")
        with self.assertRaises(PreparationStopped):
            self.prepare()
        self.assertEqual(self.calls["stage"], 1)

    def test_final_audio_callbacks_cannot_mix_changed_source_into_success(self):
        for count in (2, 3, 4, 5, 6):
            for field, value in (("text", "changed"), ("gapSeconds", 0), ("selectedTakeId", None)):
                with self.subTest(load=count, field=field):
                    self.setUp()
                    self.select()
                    def edit():
                        if self.calls["load"] == count:
                            self.line[field] = value
                    self.hooks["load"] = edit
                    if count >= 5:
                        self.prepare()
                    with self.assertRaises(PreparationSourceChanged):
                        self.prepare()
                    self.assertEqual(self.service.inspect("op").state, "failed")
                    self.assertEqual(self.calls["stage"], 0 if count == 2 else 1)

    def test_cancelled_revalidation_is_sticky_and_retains_prepared_proposal(self):
        self.select()
        self.prepare()
        self.hooks["load"] = lambda: setattr(self, "cancelled", True)
        with self.assertRaises(PreparationCancelled):
            self.prepare()
        attempt = self.service.inspect("op")
        self.assertEqual(attempt.state, "cancelled")
        self.assertIsNotNone(attempt.audio)
        self.assertEqual(attempt.staging_receipt, "fixture-staging-receipt")
        self.cancelled = False
        with self.assertRaises(PreparationStopped):
            self.prepare()

    def test_unrelated_revision_change_is_not_source_change(self):
        self.hooks["lab"] = lambda: self.project.update(revision=9)
        self.assertEqual(self.prepare().state, "prepared")

    def test_invalid_pcm_lab_or_provenance_never_reaches_staging(self):
        for content in (b"", b"0 99999 a\n", b"1 100000 a\n", b"0 100001 a\n", b"0 100000 unknown\n", b"0 50000 a\n40000 100000 i\n"):
            with self.subTest(lab=content):
                self.setUp()
                self.lab = content
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertEqual(self.calls["stage"], 0)
        self.setUp()
        self.audio = fixture_wav()[:-2]
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.calls["lab"], 0)
        self.setUp()
        dependencies = replace(self.service.dependencies, derive_lab=lambda audio, checkpoint: ProposedLab(self.lab, "a" * 64, "stub"))
        service = MotionPreparationService(dependencies)
        with self.assertRaises(ValueError):
            service.prepare(self.request, lambda: False)
        self.assertEqual(self.calls["stage"], 0)

    def test_operation_capacity_refuses_eviction_of_unadopted_proposals(self):
        self.service.max_operations = 1
        self.prepare()
        with self.assertRaises(PreparationStopped):
            self.service.prepare(replace(self.request, operation_id="other-op"), lambda: False)
        self.assertEqual(self.service.inspect("op").audio.take_id, "new")


if __name__ == "__main__":
    unittest.main()

"""Composed preparation/retained artifact checks, owned fixture data only."""
from dataclasses import replace
from io import BytesIO
import hashlib
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
import wave

from server.modules.motion_local_staging import LocalMotionStager
from server.modules.motion_preparation import (
    MotionPreparationService, PreparationDependencies, PreparationStopped, PreparationCancelled,
)
from server.modules.motion_preparation_artifacts import PreparationRequest, PreparationSnapshot, ProposedAudio, ProposedLab
from server.modules.motion_source import resolve_motion_source


class MotionStagingReplayTests(unittest.TestCase):
    def setup_pipeline(self):
        root = Path(self.enterContext(TemporaryDirectory())).resolve()
        stager = self.enterContext(LocalMotionStager(root))
        request = PreparationRequest("operation", "project", "scene", "line")
        project = {"id": "project", "revision": 1, "settings": {"lineGap": 0.25}, "scenes": [{
            "id": "scene", "lines": [{"id": "line", "characterId": "cast", "text": "試験の原文。",
                                       "takes": [{"id": "take"}], "selectedTakeId": "take"}]}]}
        source = resolve_motion_source(project, "scene", "line", lambda _: True)
        snapshot = PreparationSnapshot(source, "fixture-inputs")
        stream = BytesIO()
        with wave.open(stream, "wb") as writer:
            writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            writer.writeframes(b"\x01\x00" * 16000)
        audio = ProposedAudio("take", stream.getvalue())
        lab = ProposedLab(b"0 10000000 pau\n", hashlib.sha256(audio.wav).hexdigest(), "fixture-stub")
        calls = {"stage": 0, "generate": 0, "lab": 0}
        def generate(*_):
            calls["generate"] += 1
            self.fail("Selected fixture must not generate.")
        def derive(*_):
            calls["lab"] += 1
            return lab
        def stage(bundle, checkpoint):
            calls["stage"] += 1
            return stager.stage(request, bundle, checkpoint)
        service = MotionPreparationService(PreparationDependencies(
            lambda _: snapshot, lambda *_: audio, generate, derive, stage, stager.verify,
        ))
        first = service.prepare(request, lambda: False)
        output = root / stager.inspect(request.operation_id).receipt.directory
        return root, stager, request, service, first, output, calls

    def assert_failed_replay(self, stager, request, service, first, calls):
        with self.assertRaises((ValueError, OSError)):
            service.prepare(request, lambda: False)
        attempt = service.inspect(request.operation_id)
        self.assertEqual(attempt.state, "failed")
        self.assertEqual(attempt.bundle, first.bundle)
        self.assertEqual(attempt.staging_receipt, first.staging_receipt)
        self.assertEqual(stager.inspect(request.operation_id).state, "failed")
        self.assertEqual(calls, {"stage": 1, "generate": 0, "lab": 1})
        with self.assertRaises(PreparationStopped):
            service.prepare(request, lambda: False)

    def test_valid_replay_verifies_without_republishing_or_reanalysis(self):
        root, stager, request, service, first, output, calls = self.setup_pipeline()
        before = {p.name: (p.read_bytes(), p.stat().st_ino) for p in output.iterdir()}
        replay = service.prepare(request, lambda: False)
        self.assertEqual(replay.state, "prepared")
        self.assertEqual(replay.staging_receipt, first.staging_receipt)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_ino) for p in output.iterdir()})
        self.assertEqual(calls, {"stage": 1, "generate": 0, "lab": 1})
        self.assertEqual(len(list(root.iterdir())), 1)

    def test_each_corrupt_or_missing_artifact_fails_the_composed_service(self):
        for extension in ("wav", "txt", "lab"):
            for missing in (False, True):
                with self.subTest(extension=extension, missing=missing):
                    _, stager, request, service, first, output, calls = self.setup_pipeline()
                    target = output / f"dialogue.{extension}"
                    if missing:
                        target.unlink()
                    else:
                        target.write_bytes(b"corrupted owned fixture")
                    self.assert_failed_replay(stager, request, service, first, calls)

    def test_identical_byte_file_replacement_is_not_the_retained_identity(self):
        _, stager, request, service, first, output, calls = self.setup_pipeline()
        target = output / "dialogue.txt"
        replacement = output / "replacement"
        replacement.write_bytes(target.read_bytes())
        os.replace(replacement, target)
        self.assert_failed_replay(stager, request, service, first, calls)

    def test_directory_replacement_with_identical_files_fails(self):
        root, stager, request, service, first, output, calls = self.setup_pipeline()
        replacement = root / "replacement"
        shutil.copytree(output, replacement)
        output.rename(root / "old-owned-output")
        replacement.rename(output)
        self.assert_failed_replay(stager, request, service, first, calls)

    def test_symlink_or_fifo_is_refused_without_touching_other_data(self):
        for fifo in (False, True):
            with self.subTest(fifo=fifo):
                root, stager, request, service, first, output, calls = self.setup_pipeline()
                sentinel = root / "unrelated-sentinel"
                sentinel.write_bytes(b"keep unrelated data")
                target = output / "dialogue.txt"
                target.unlink()
                if fifo:
                    os.mkfifo(target)
                else:
                    target.symlink_to(sentinel)
                self.assert_failed_replay(stager, request, service, first, calls)
                self.assertEqual(sentinel.read_bytes(), b"keep unrelated data")

    def test_receipt_metadata_and_path_tampering_are_not_success(self):
        for field, value in (("token", "wrong"), ("directory", "../outside"),
                             ("digests", ("a" * 64,) * 3), ("content_version", "wrong"),
                             ("request", PreparationRequest("other", "project", "scene", "line"))):
            with self.subTest(field=field):
                root, stager, request, service, first, output, calls = self.setup_pipeline()
                before = {p.name: p.read_bytes() for p in output.iterdir()}
                retained = stager._attempts[request.operation_id]
                retained.receipt = replace(retained.receipt, **{field: value})
                self.assert_failed_replay(stager, request, service, first, calls)
                self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})
                self.assertEqual(len(list(root.iterdir())), 1)

    def test_root_replacement_fails_without_using_new_root(self):
        root, stager, request, service, first, output, calls = self.setup_pipeline()
        old = root.with_name(root.name + "-retained")
        root.rename(old)
        self.addCleanup(shutil.rmtree, old)
        root.mkdir()
        sentinel = root / "unrelated-sentinel"
        sentinel.write_bytes(b"new root sentinel")
        self.assert_failed_replay(stager, request, service, first, calls)
        self.assertEqual(sentinel.read_bytes(), b"new root sentinel")

    def test_verification_cancellation_is_sticky_and_preserves_receipt(self):
        _, stager, request, service, first, output, calls = self.setup_pipeline()
        verify = service.dependencies.verify_staging
        def cancelled_verify(req, bundle, token, checkpoint):
            verify(req, bundle, token, lambda: (_ for _ in ()).throw(PreparationCancelled("fixture")))
        service.dependencies = replace(service.dependencies, verify_staging=cancelled_verify)
        with self.assertRaises(PreparationCancelled):
            service.prepare(request, lambda: False)
        attempt = service.inspect(request.operation_id)
        self.assertEqual(attempt.state, "cancelled")
        self.assertEqual(attempt.staging_receipt, first.staging_receipt)
        self.assertEqual(stager.inspect(request.operation_id).state, "cancelled")
        self.assertEqual(len(list(output.iterdir())), 3)


if __name__ == "__main__":
    unittest.main()

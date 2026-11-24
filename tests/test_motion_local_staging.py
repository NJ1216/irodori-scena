from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
import wave

from server.modules.motion_local_staging import LocalMotionStager
from server.modules.motion_preparation import PreparationCancelled, PreparationStopped
from server.modules.motion_preparation_artifacts import PreparationRequest, PreparationSnapshot, ProposedAudio, ProposedLab, assemble_bundle
from server.modules.motion_source import resolve_motion_source


class LocalMotionStagingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.stager = self.enterContext(LocalMotionStager(self.root))
        self.request = PreparationRequest("operation", "project", "scene", "line")
        project = {"id": "project", "revision": 1, "settings": {"lineGap": 0.25}, "scenes": [{
            "id": "scene", "lines": [{"id": "line", "characterId": "cast", "text": "原文🙂\nそのまま。",
                                       "takes": [{"id": "take"}], "selectedTakeId": "take"}]}]}
        source = resolve_motion_source(project, "scene", "line", lambda _take: True)
        buffer = BytesIO()
        with wave.open(buffer, "wb") as writer:
            writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            writer.writeframes(b"\x01\x00" * 160)
        audio = ProposedAudio("take", buffer.getvalue())
        lab = ProposedLab(b"0 100000 pau\n", hashlib.sha256(audio.wav).hexdigest(), "fixture-v1")
        self.bundle = assemble_bundle(PreparationSnapshot(source, "fixture-inputs"), audio, lab)

    def stage(self, checkpoint=lambda: None):
        return self.stager.stage(self.request, self.bundle, checkpoint)

    def test_wav_txt_lab_are_exact_and_duplicate_request_returns_same_receipt(self):
        token = self.stage()
        attempt = self.stager.inspect("operation")
        output = self.root / attempt.receipt.directory
        self.assertEqual(attempt.state, "staged")
        self.assertEqual((output / "dialogue.wav").read_bytes(), self.bundle.audio.wav)
        self.assertEqual((output / "dialogue.txt").read_bytes(), self.bundle.dialogue_txt)
        self.assertEqual((output / "dialogue.lab").read_bytes(), self.bundle.lab.content)
        self.assertEqual(set(path.name for path in output.iterdir()), {"dialogue.wav", "dialogue.txt", "dialogue.lab"})
        self.assertEqual(self.stage(), token)
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_opaque_traversal_operation_id_never_becomes_a_path(self):
        self.request = replace(self.request, operation_id="../../outside/日本語")
        self.stage()
        directory = self.stager.inspect(self.request.operation_id).receipt.directory
        self.assertTrue(directory.startswith("prepared-"))
        self.assertEqual(Path(directory).parts, (directory,))
        self.assertTrue((self.root / directory).is_dir())

    def test_root_symlink_parent_traversal_and_output_symlink_are_refused(self):
        link = self.root / "linked-root"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            LocalMotionStager(link)
        with self.assertRaises(ValueError):
            LocalMotionStager(self.root / ".." / self.root.name)
        outside = Path(self.enterContext(TemporaryDirectory()))
        target = self.root / self.stager._directory(self.request)
        target.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FileExistsError):
            self.stage()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIsNone(self.stager.inspect("operation").receipt)

    def test_existing_output_or_new_instance_is_not_overwritten_or_adopted(self):
        self.stage()
        receipt = self.stager.inspect("operation").receipt
        output = self.root / receipt.directory
        before = {path.name: path.read_bytes() for path in output.iterdir()}
        with LocalMotionStager(self.root) as other:
            with self.assertRaises(FileExistsError):
                other.stage(self.request, self.bundle, lambda: None)
            self.assertIsNone(other.inspect("operation").receipt)
        self.assertEqual(before, {path.name: path.read_bytes() for path in output.iterdir()})
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_changed_content_or_other_source_for_same_operation_is_rejected(self):
        self.stage()
        snapshot = replace(self.bundle.snapshot, source=replace(self.bundle.snapshot.source, body="changed"))
        changed = assemble_bundle(snapshot, self.bundle.audio, self.bundle.lab)
        with self.assertRaises(ValueError):
            self.stager.stage(self.request, changed, lambda: None)
        with self.assertRaises(ValueError):
            self.stager.stage(replace(self.request, line_id="other"), self.bundle, lambda: None)

    def test_short_writes_complete_but_zero_or_failed_writes_have_no_receipt(self):
        original = os.write
        with patch("server.modules.motion_local_staging.os.write", side_effect=lambda fd, data: original(fd, data[:7])):
            self.stage()
        for name, callback in (("zero", lambda fd, data: 0), ("failed", lambda fd, data: (_ for _ in ()).throw(OSError("fixture failure")))):
            request = replace(self.request, operation_id=name)
            with patch("server.modules.motion_local_staging.os.write", side_effect=callback):
                with self.assertRaises(OSError):
                    self.stager.stage(request, self.bundle, lambda: None)
            attempt = self.stager.inspect(name)
            self.assertEqual(attempt.state, "failed")
            self.assertIsNone(attempt.receipt)
            self.assertIsNotNone(attempt.partial_directory)
            with self.assertRaises(PreparationStopped):
                self.stager.stage(request, self.bundle, lambda: None)

    def test_failed_partial_publication_has_no_receipt_and_cannot_retry(self):
        original = os.link
        calls = [0]
        def fail_second(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 2:
                raise OSError("fixture publication failure")
            return original(*args, **kwargs)
        with patch("server.modules.motion_local_staging.os.link", side_effect=fail_second):
            with self.assertRaises(OSError):
                self.stage()
        attempt = self.stager.inspect("operation")
        self.assertEqual(attempt.state, "failed")
        self.assertIsNone(attempt.receipt)
        self.assertTrue((self.root / attempt.output_directory / "dialogue.wav").is_file())
        self.assertFalse((self.root / attempt.output_directory / "dialogue.lab").exists())
        with self.assertRaises(PreparationStopped):
            self.stage()

    def test_cancel_after_three_links_retains_files_without_success_receipt(self):
        original = os.link
        count = [0]
        def link(*args, **kwargs):
            result = original(*args, **kwargs)
            count[0] += 1
            return result
        def checkpoint():
            if count[0] == 3:
                raise PreparationCancelled("fixture cancellation")
        with patch("server.modules.motion_local_staging.os.link", side_effect=link):
            with self.assertRaises(PreparationCancelled):
                self.stage(checkpoint)
        attempt = self.stager.inspect("operation")
        self.assertEqual(attempt.state, "cancelled")
        self.assertIsNone(attempt.receipt)
        self.assertEqual(len(list((self.root / attempt.output_directory).iterdir())), 3)

    def test_replay_rejects_symlinked_or_modified_output_without_following_it(self):
        self.stage()
        attempt = self.stager.inspect("operation")
        target = self.root / attempt.output_directory / "dialogue.txt"
        outside = Path(self.enterContext(TemporaryDirectory())) / "unrelated.txt"
        outside.write_bytes(b"external sentinel")
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaises(OSError):
            self.stage()
        self.assertEqual(outside.read_bytes(), b"external sentinel")
        self.assertEqual(self.stager.inspect("operation").state, "failed")

    def test_tampered_metadata_or_txt_never_writes_output(self):
        for changed in (replace(self.bundle, frame_count=999), replace(self.bundle, dialogue_txt=b"incorrect")):
            with self.assertRaises(ValueError):
                self.stager.stage(self.request, changed, lambda: None)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_fifo_or_truncated_output_is_refused_and_keeps_only_historical_receipt(self):
        self.stage()
        prior = self.stager.inspect("operation")
        target = self.root / prior.output_directory / "dialogue.txt"
        target.unlink()
        os.mkfifo(target)
        with self.assertRaises(ValueError):
            self.stage()
        after = self.stager.inspect("operation")
        self.assertEqual(after.state, "failed")
        self.assertEqual(after.receipt, prior.receipt)
        self.request = replace(self.request, operation_id="truncated")
        self.stage()
        target = self.root / self.stager.inspect("truncated").output_directory / "dialogue.wav"
        target.write_bytes(self.bundle.audio.wav[:-1])
        with self.assertRaises(ValueError):
            self.stage()
        self.assertEqual(self.stager.inspect("truncated").state, "failed")

    def test_replaced_root_invalidates_replay_instead_of_claiming_staged(self):
        self.stage()
        prior = self.stager.inspect("operation").receipt
        owner = Path(self.enterContext(TemporaryDirectory()))
        self.root.rename(owner / "original-root")
        self.root.mkdir()
        with self.assertRaises(ValueError):
            self.stage()
        after = self.stager.inspect("operation")
        self.assertEqual(after.state, "failed")
        self.assertEqual(after.receipt, prior)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_partial_only_restart_is_not_durable_deduplication_or_recovery(self):
        with patch("server.modules.motion_local_staging.os.write", return_value=0):
            with self.assertRaises(OSError):
                self.stage()
        partial = self.stager.inspect("operation").partial_directory
        with LocalMotionStager(self.root) as restarted:
            restarted.stage(self.request, self.bundle, lambda: None)
            self.assertEqual(restarted.inspect("operation").state, "staged")
        self.assertTrue((self.root / partial).is_dir())
        self.assertEqual(self.stager.inspect("operation").state, "failed")

    def test_concurrent_duplicate_stages_once(self):
        results, errors = [], []
        def run():
            try:
                results.append(self.stage())
            except Exception as error:
                errors.append(error)
        workers = [threading.Thread(target=run) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(list(self.root.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()

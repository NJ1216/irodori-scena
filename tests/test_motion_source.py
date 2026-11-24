from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

from server.modules.motion_source import motion_content_version, resolve_motion_source
from server.modules.timeline_identity import audio_identity


class MotionSourceTests(unittest.TestCase):
    def setUp(self):
        self.project = {
            "id": "project", "revision": 2, "settings": {"lineGap": 0.7},
            "scenes": [{"id": "scene", "lines": [{
                "id": "line", "characterId": "cast", "text": "本文🙂\nそのまま。",
                "stageDirection": "this must not become the body", "takes": [], "selectedTakeId": None,
            }]}],
        }
        self.line = self.project["scenes"][0]["lines"][0]

    def source(self, available=lambda _take: True):
        return resolve_motion_source(self.project, "scene", "line", available)

    def version(self, source=None, **kwargs):
        wav = hashlib.sha256(b"wav content").hexdigest()
        options = {
            "take_id": "new", "wav_sha256": wav, "lab_wav_sha256": wav,
            "lab_sha256": hashlib.sha256(b"0 10000000 a\n").hexdigest(), "analysis_identity": "stub-v1",
        }
        options.update(kwargs)
        return motion_content_version(source or self.source(), **options)

    def test_unselected_zero_one_and_multiple_old_takes_require_generation(self):
        for count in (0, 1, 3):
            with self.subTest(count=count):
                self.line["takes"] = [{"id": f"old-{index}"} for index in range(count)]
                before = deepcopy(self.project)
                source = self.source(lambda _take: self.fail("Unselected audio must not be probed."))
                self.assertTrue(source.needs_generation)
                self.assertEqual(source.generation_reason, "unselected")
                self.assertIsNone(source.selected_take)
                self.assertEqual(self.project, before)

    def select(self):
        self.line.update(takes=[{"id": "chosen", "audioUrl": "/media/takes/chosen.wav"}], selectedTakeId="chosen")

    def test_valid_selection_and_detached_take(self):
        self.select()
        source = self.source()
        self.assertFalse(source.needs_generation)
        self.line["takes"][0]["audioUrl"] = "changed"
        self.assertEqual(source.selected_take["audioUrl"], "/media/takes/chosen.wav")

    def test_missing_record_and_unavailable_audio_do_not_use_old_siblings(self):
        self.select()
        self.line["takes"].append({"id": "old"})
        self.assertEqual(self.source(lambda _take: False).generation_reason, "unavailable_audio")
        self.line["selectedTakeId"] = "missing"
        self.assertEqual(self.source().generation_reason, "missing_record")
        self.assertEqual([take["id"] for take in self.line["takes"]], ["chosen", "old"])

    def test_unexpected_probe_failure_propagates(self):
        self.select()
        def fail(_take):
            raise PermissionError("fixture denial")
        with self.assertRaises(PermissionError):
            self.source(fail)

    def test_probe_cannot_mix_project_or_take_state_into_snapshot(self):
        self.select()
        def probe(take):
            self.line.update(text="edited", gapSeconds=2, selectedTakeId="other")
            take["id"] = "modified probe copy"
            return True
        source = self.source(probe)
        self.assertEqual(source.body, "本文🙂\nそのまま。")
        self.assertEqual(source.gap_seconds, 0.7)
        self.assertEqual(source.selected_take_id, "chosen")
        self.assertEqual(source.selected_take["id"], "chosen")

    def test_missing_and_duplicate_logical_identities_are_rejected(self):
        for kind in ("project", "scene", "line", "cast", "duplicate_scene", "duplicate_line", "duplicate_take"):
            with self.subTest(kind=kind):
                project = deepcopy(self.project)
                line = project["scenes"][0]["lines"][0]
                if kind == "project":
                    project["id"] = ""
                elif kind == "scene":
                    project["scenes"][0]["id"] = "other"
                elif kind == "line":
                    line["id"] = "other"
                elif kind == "cast":
                    line["characterId"] = ""
                elif kind == "duplicate_scene":
                    project["scenes"].append(deepcopy(project["scenes"][0]))
                elif kind == "duplicate_line":
                    project["scenes"].append({"id": "other", "lines": [deepcopy(line)]})
                else:
                    line.update(selectedTakeId="same", takes=[{"id": "same"}, {"id": "same"}])
                with self.assertRaises(ValueError):
                    resolve_motion_source(project, "scene", "line", lambda _take: True)

    def test_reorder_preserves_identity_and_deleted_target_fails(self):
        other = {"id": "other", "lines": []}
        self.project["scenes"].insert(0, other)
        self.assertEqual(self.source().line_id, "line")
        self.project["scenes"][1]["lines"] = []
        with self.assertRaises(ValueError):
            self.source()

    def test_gap_zero_negative_missing_and_invalid_preserve_source_semantics(self):
        for value in (0, -0.25, 0.5):
            self.line["gapSeconds"] = value
            source = self.source()
            self.assertEqual((source.gap_seconds, source.gap_source), (value, "line"))
        self.line["gapSeconds"] = None
        self.assertEqual(self.source().gap_source, "project")
        self.project["settings"]["lineGap"] = None
        source = self.source()
        self.assertEqual((source.gap_seconds, source.gap_source), (None, "unspecified"))
        with self.assertRaises(ValueError):
            self.version(source)
        for value in (True, "0.5", float("nan"), float("inf")):
            self.line["gapSeconds"] = value
            with self.assertRaises(ValueError):
                self.source()

    def test_body_is_verbatim_and_revision_and_selection_do_not_version_content(self):
        source = self.source()
        self.assertEqual(source.body, self.line["text"])
        self.assertEqual(self.version(source), self.version(replace(source, project_revision=100)))
        selected = replace(source, selected_take_id="new", selected_take={"id": "new"}, generation_reason=None)
        self.assertEqual(self.version(source), self.version(selected))

    def test_body_gap_cast_take_lab_and_analysis_changes_version_content(self):
        source, version = self.source(), self.version()
        for field, value in (("body", "changed"), ("gap_seconds", 0.8), ("character_id", "other")):
            self.assertNotEqual(version, self.version(replace(source, **{field: value})))
        for options in ({"take_id": "other"}, {"lab_sha256": "a" * 64}, {"analysis_identity": "stub-v2"}):
            self.assertNotEqual(version, self.version(**options))

    def test_signed_zero_interval_has_the_same_content_version(self):
        source = self.source()
        self.assertEqual(self.version(replace(source, gap_seconds=0.0)), self.version(replace(source, gap_seconds=-0.0)))

    def test_mismatched_lab_provenance_and_prepared_take_are_rejected(self):
        with self.assertRaises(ValueError):
            self.version(lab_wav_sha256="a" * 64)
        with self.assertRaises(ValueError):
            self.version(lab_sha256="not a digest")
        self.select()
        with self.assertRaises(ValueError):
            self.version(self.source(), take_id="other")

    def test_required_generation_rejects_old_and_missing_selected_take_ids(self):
        self.select()
        for selection in (None, "chosen", "missing"):
            with self.subTest(selection=selection):
                self.line["selectedTakeId"] = selection
                source = self.source(lambda _take: False)
                for old_id in ("chosen", "missing") if selection == "missing" else ("chosen",):
                    with self.assertRaises(ValueError):
                        self.version(source, take_id=old_id)
                self.assertTrue(self.version(source, take_id="new"))

    def test_path_only_copy_is_unchanged_but_same_id_path_overwrite_is_changed(self):
        with TemporaryDirectory() as directory:
            path, copy = Path(directory) / "chosen.wav", Path(directory) / "copied.wav"
            def write(samples):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    writer.writeframes(samples)
            write(b"\x01\x00" * 160)
            copy.write_bytes(path.read_bytes())
            before, stat = audio_identity(path), path.stat()
            def version(digest):
                return self.version(wav_sha256=digest, lab_wav_sha256=digest)
            self.assertEqual(version(before), version(audio_identity(copy)))
            write(b"\x02\x00" * 160)
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            self.assertEqual(path.stat().st_size, stat.st_size)
            self.assertNotEqual(version(before), version(audio_identity(path)))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules.timeline import place_units, interval_inputs, project_timeline
from server.modules.timeline_intervals import describe_interval
from server.modules.timeline_queue import IntervalQueue


class TimelineTests(unittest.TestCase):
    def test_shared_placement_fixture(self):
        fixtures = json.loads(Path("tests/fixtures/timeline/placement.json").read_text())
        for fixture in fixtures:
            with self.subTest(fixture["name"]):
                units = place_units(fixture["units"])
                self.assertEqual([u["start"] for u in units], fixture["starts"])
                self.assertEqual([u["resolved"] for u in units], fixture["resolved"])
                self.assertEqual(max(u["start"] + u["duration"] for u in units), fixture["end"])
                self.assertEqual([u["gap"] for u in units], [u["gap"] for u in fixture["units"]])

    def test_unknown_later_audio_does_not_block_known_positive_gap_intro(self):
        units = place_units(
            [
                {"gap": 0, "members": [{"id": "a", "duration": 5000}]},
                {"gap": 0, "members": [{"id": "b", "duration": None}]},
            ]
        )
        plan = {"sampleRate": 1000, "units": units}
        self.assertEqual(interval_inputs(plan, 0, 1000)[1], [])
        self.assertEqual(interval_inputs(plan, 4000, 5000)[1], ["b"])

    def test_far_negative_gap_and_predecessors_are_dependencies(self):
        units = place_units(
            [
                {"gap": 0, "members": [{"id": "a", "duration": 5000}]},
                {"gap": -10000, "members": [{"id": "b", "duration": None}]},
                {"gap": 0, "members": [{"id": "c", "duration": None}]},
            ]
        )
        self.assertEqual(interval_inputs({"sampleRate": 1000, "units": units}, 0, 1000)[1], ["b", "c"])

    def test_excluded_earlier_numbers_still_determine_placement(self):
        units = place_units(
            [
                {"gap": 1000, "members": [{"id": "a", "duration": 3000}]},
                {"gap": -5000, "members": [{"id": "b", "duration": 2000}]},
                {"gap": 0, "members": [{"id": "c", "duration": 7000}]},
            ]
        )
        inputs, missing = interval_inputs({"sampleRate": 1000, "units": units}, 4000, 5000, {"b", "c"})
        self.assertEqual([(m["id"], m["start"]) for m in inputs], [("b", 4000), ("c", 1000)])
        self.assertEqual(missing, [])

    def test_project_filters_invalid_lines_and_uses_wav_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "take.wav"
            with wave.open(str(path), "wb") as writer:
                writer.setparams((1, 2, 1000, 0, "NONE", "not compressed"))
                writer.writeframes(b"\0" * 6000)

            def line(key, **changes):
                return {
                    "id": key,
                    "text": key,
                    "characterId": "cast",
                    "takes": [{"id": "t", "audioUrl": "x", "durationSeconds": 99}],
                    "selectedTakeId": "t",
                    **changes,
                }

            project = {
                "id": "p",
                "settings": {"lineGap": -2},
                "scenes": [
                    {
                        "lines": [
                            line("disabled", enabled=False),
                            line("empty", text=" "),
                            line("no-cast", characterId=""),
                            line("a"),
                        ]
                    },
                    {"lines": [line("b"), line("c")]},
                ],
            }
            with (
                patch("server.modules.export_service.take_audio_path", return_value=path),
                patch("server.modules.cue_mix.audio_file_identity", return_value="hash"),
            ):
                plan = project_timeline(project)
            self.assertEqual([u["id"] for u in plan["units"]], ["a", "b", "c"])
            self.assertEqual([u["start"] for u in plan["units"]], [0, 1000, 2000])
            self.assertEqual(plan["endFrame"], 5000)

    def test_silence_is_distinct_from_waiting_input_and_signature_covers_targets(self):
        plan = {
            "planId": "p",
            "generation": 1,
            "sampleRate": 1000,
            "units": place_units([{"gap": 0, "members": [{"id": "a", "duration": 500}]}]),
        }
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.MEDIA_ROOT", Path(directory)):
            empty = describe_interval(plan, 2000, 3000)
            self.assertEqual(empty["status"], "silence")
            self.assertNotEqual(empty["intervalId"], describe_interval(plan, 2000, 3000, set())["intervalId"])

    def test_absent_legacy_boundary_is_422(self):
        from fastapi import HTTPException
        from server.modules.derived_audio_preparation import request_overlap
        from types import SimpleNamespace

        with patch(
            "server.modules.derived_audio_preparation._current_plan", return_value=SimpleNamespace(boundaries={})
        ):
            with self.assertRaises(HTTPException) as caught:
                request_overlap("absent")
        self.assertEqual(caught.exception.status_code, 422)

    def test_queue_promotes_active_required_work_without_cancellation(self):
        from server.modules.timeline_queue import Work

        queue = IntervalQueue()
        interval = {"intervalId": "a", "status": "rendering"}
        queue.active = Work(interval, 10, 1)
        queue.work["a"] = queue.active
        with patch("threading.Thread"):
            queue.submit([{**interval, "status": "queued"}])
        self.assertFalse(queue.active.cancel.is_set())
        self.assertEqual(queue.active.priority, 0)

    def test_stopped_session_and_late_generation_cannot_resume(self):
        from server.modules import timeline_sessions as sessions
        from fastapi import HTTPException

        sessions.accept("test-client", 1, "old", "workspace")
        sessions.stop("test-client", 1, "old")
        with self.assertRaises(HTTPException):
            sessions.accept("test-client", 1, "old", "workspace")
        sessions.accept("test-client", 2, "new", "workspace")
        sessions.stop("test-client", 1, "old")
        sessions.accept("test-client", 2, "new", "workspace")
        with self.assertRaises(HTTPException):
            sessions.accept("test-client", 2, "new", "different-workspace")

    def test_missing_selected_wav_keeps_anchor_and_waits_for_input(self):
        from server.modules.timeline import project_timeline

        project = {
            "id": "p",
            "settings": {"lineGap": 0},
            "scenes": [
                {
                    "lines": [
                        {
                            "id": "a",
                            "text": "a",
                            "characterId": "cast",
                            "selectedTakeId": "take",
                            "takes": [{"id": "take", "audioUrl": "missing"}],
                        }
                    ]
                }
            ],
        }
        with patch(
            "server.modules.export_service.take_audio_path", side_effect=RuntimeError("Selected take WAV is missing.")
        ):
            plan = project_timeline(project)
        self.assertEqual(plan["units"][0]["start"], 0)
        self.assertIsNone(plan["units"][0]["members"][0]["duration"])
        self.assertEqual(interval_inputs(plan, 0, 48000)[1], ["a"])

    def test_same_size_wav_replacement_with_preserved_mtime_changes_signature(self):
        import os
        from server.modules.timeline_identity import audio_identity

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wave.wav"
            path.write_bytes(b"first")
            before = path.stat()
            original = audio_identity(path)
            replacement = Path(directory) / "replacement.wav"
            replacement.write_bytes(b"other")
            os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
            replacement.replace(path)
            self.assertNotEqual(original, audio_identity(path))

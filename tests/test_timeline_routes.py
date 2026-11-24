from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
import server.app  # noqa: F401
from server.modules.timeline import place_units
from server.modules.timeline_routes import IntervalRequest, prepare_timeline_intervals
from server.modules.timeline_queue import IntervalQueue, Work
from server.modules.timeline_intervals import describe_interval, background_intervals


def plan():
    return {
        "planId": "plan",
        "generation": 1,
        "projectId": "p",
        "sampleRate": 1000,
        "resolved": True,
        "endFrame": 3500,
        "units": place_units([{"gap": 0, "members": [{"id": "a", "duration": 3500, "offset": 0}]}]),
    }


class TimelineRouteTests(unittest.TestCase):
    def test_prepares_only_current_and_next_two_intervals(self):
        request = IntervalRequest(
            project_id="p", plan_id="plan", start_frame=0, client_id="test", playback_id="test", sequence=1
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("server.modules.constants.MEDIA_ROOT", Path(directory)),
            patch("server.modules.timeline_routes._plan", return_value=plan()),
            patch("server.modules.timeline_routes.QUEUE.submit", side_effect=lambda items: items) as submit,
        ):
            result = prepare_timeline_intervals(request)
        self.assertEqual(
            [(item["startFrame"], item["endFrame"]) for item in result["intervals"]],
            [(0, 1000), (1000, 2000), (2000, 3000)],
        )
        self.assertEqual(submit.call_count, 1)
        self.assertNotIn("inputs", result["intervals"][0])

    def test_stale_plan_is_returned_without_queuing_old_audio(self):
        request = IntervalRequest(
            project_id="p", plan_id="old", start_frame=0, client_id="test", playback_id="test", sequence=1
        )
        with (
            patch("server.modules.timeline_routes._plan", return_value=plan()),
            patch("server.modules.timeline_routes.QUEUE.submit") as submit,
        ):
            result = prepare_timeline_intervals(request)
        self.assertEqual(result["status"], "stale")
        submit.assert_not_called()

    def test_project_identity_is_checked_before_preparing(self):
        request = IntervalRequest(
            project_id="p", plan_id="plan", start_frame=0, client_id="test", playback_id="test", sequence=1
        )
        with patch("server.modules.project_repository.read_project", return_value={"id": "different"}):
            with self.assertRaises(HTTPException) as caught:
                prepare_timeline_intervals(request)
        self.assertEqual(caught.exception.status_code, 409)

    def test_unrelated_active_work_is_cancelled_before_nearby_work_runs(self):
        queue = IntervalQueue()
        queue.active = Work({"intervalId": "far", "status": "rendering"}, 10, 1)
        queue.work["far"] = queue.active
        with patch.object(queue, "_ensure_worker"):
            queue.submit([{"intervalId": "near", "status": "queued"}])
        self.assertTrue(queue.active.cancel.is_set())
        self.assertEqual(queue.work["near"].priority, 0)

    def test_background_refresh_retains_unchanged_active_signature(self):
        queue = IntervalQueue()
        original = plan()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("server.modules.constants.MEDIA_ROOT", Path(directory)),
            patch.object(queue, "_ensure_worker"),
        ):
            item = describe_interval(original, 0, 1000)
            queue.active = Work(item, 0, 1)
            queue.work[item["intervalId"]] = queue.active
            changed = {**original, "planId": "changed", "generation": 2}
            queue.background_plan(changed)
            self.assertFalse(queue.active.cancel.is_set())
            self.assertEqual(queue.active.priority, 0)
            changed["units"][0]["members"][0]["signature"] = "new-wav"
            changed["planId"] = "changed-again"
            queue.background_plan(changed)
            self.assertTrue(queue.active.cancel.is_set())

    def test_background_skips_large_silent_gaps_without_materializing_them(self):
        value = plan()
        value["units"] = place_units(
            [
                {"gap": 10000000, "members": [{"id": "a", "duration": 1000, "offset": 0}]},
                {"gap": 0, "members": [{"id": "b", "duration": 1000, "offset": 0}]},
            ]
        )
        value["endFrame"] = 10002000
        with tempfile.TemporaryDirectory() as directory, patch("server.modules.constants.MEDIA_ROOT", Path(directory)):
            intervals = list(background_intervals(value))
        self.assertEqual([item["startFrame"] for item in intervals], [0, 10001000])

    def test_short_ready_intro_is_published_before_a_missing_zero_gap_successor(self):
        value = plan()
        value["resolved"] = False
        value["units"] = place_units(
            [
                {"gap": 0, "members": [{"id": "a", "duration": 400, "offset": 0}]},
                {"gap": 0, "members": [{"id": "b", "duration": None, "offset": 0}]},
            ]
        )
        request = IntervalRequest(
            project_id="p", plan_id="plan", start_frame=0, client_id="test", playback_id="test", sequence=1
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("server.modules.constants.MEDIA_ROOT", Path(directory)),
            patch("server.modules.timeline_routes._plan", return_value=value),
            patch("server.modules.timeline_routes.QUEUE.submit", side_effect=lambda items: items),
        ):
            intervals = prepare_timeline_intervals(request)["intervals"]
        self.assertEqual(intervals[0]["status"], "queued")
        self.assertEqual(intervals[0]["endFrame"], 250)
        self.assertEqual(intervals[1]["startFrame"], 250)
        self.assertEqual(intervals[1]["status"], "waiting-input")

    def test_selected_tail_is_short_even_when_excluded_later_audio_is_missing(self):
        value = plan()
        value["resolved"] = False
        value["units"] = place_units(
            [
                {"gap": 0, "members": [{"id": "a", "duration": 400, "offset": 0}]},
                {"gap": 0, "members": [{"id": "b", "duration": None, "offset": 0}]},
            ]
        )
        request = IntervalRequest(
            project_id="p",
            plan_id="plan",
            start_frame=0,
            target_line_ids=["a"],
            client_id="test",
            playback_id="test",
            sequence=1,
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("server.modules.constants.MEDIA_ROOT", Path(directory)),
            patch("server.modules.timeline_routes._plan", return_value=value),
            patch("server.modules.timeline_routes.QUEUE.submit", side_effect=lambda items: items),
        ):
            intervals = prepare_timeline_intervals(request)["intervals"]
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0]["endFrame"], 400)
        self.assertEqual(intervals[0]["status"], "queued")

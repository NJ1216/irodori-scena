from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch

from server.app import app as _registered_app  # noqa: F401
from server.modules import derived_audio_preparation as preparation, history


def _line(line_id: str, gap: float) -> dict[str, object]:
    take_id = f"take-{line_id}"
    return {
        "id": line_id,
        "text": line_id,
        "characterId": "cast",
        "gapSeconds": gap,
        "takes": [{"id": take_id, "audioUrl": f"/media/{take_id}.wav"}],
        "selectedTakeId": take_id,
    }


def _boundaries(*line_ids: str) -> dict[str, dict[str, object]]:
    return {
        line_id: {
            "leadingLineId": line_id,
            "signature": f"signature-{line_id}",
            "effectiveGapSeconds": -0.2,
            "previous": {},
            "following": {},
        }
        for line_id in line_ids
    }


class DerivedAudioPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep the persistent daemon parked during queue-only tests.
        preparation._CONDITION.acquire()
        self.addCleanup(preparation._CONDITION.release)
        with preparation._CONDITION:
            preparation._QUEUE.clear()
            preparation._WORK.clear()
            preparation._STATE.clear()
            preparation._PLAYBACKS.clear()
            preparation._ACTIVE_PLAYBACKS.clear()
            preparation._PLANS.clear()
            preparation._CURRENT_PROJECT_KEY = None
            preparation._ACTIVE = None
            preparation._ORDER = 0

    def tearDown(self) -> None:
        preparation._QUEUE.clear()
        preparation._PLANS.clear()
        preparation._CURRENT_PROJECT_KEY = None
        preparation._ACTIVE = None

    @contextmanager
    def running_worker(self):
        preparation._CONDITION.release()
        try:
            yield
        finally:
            preparation._CONDITION.acquire()
            preparation._CURRENT_PROJECT_KEY = None
            preparation._PLANS.clear()
            preparation._QUEUE.clear()
            if preparation._ACTIVE:
                preparation._ACTIVE.cancel.set()
            preparation._CONDITION.notify_all()
            self.assertTrue(preparation._CONDITION.wait_for(lambda: preparation._ACTIVE is None, timeout=2),
                            "Worker must finish before its render mock is removed")

    def test_playback_promotes_active_nearby_mix_without_cancelling_it(self) -> None:
        boundaries = _boundaries("one", "two", "far")
        preparation._CURRENT_PROJECT_KEY = "project"
        preparation._PLANS["project"] = preparation._Plan("project", boundaries)
        with preparation._CONDITION:
            active = preparation._enqueue("project", "one", 10)
            preparation._QUEUE.clear()
            preparation._ACTIVE = active
            preparation._enqueue("project", "far", 10)
        with patch.object(preparation, "_ensure_worker"):
            preparation.update_playback("playback", ["one", "two"], start=True)
        self.assertFalse(active.cancel.is_set())
        self.assertEqual(active.priority, 0)
        self.assertEqual([(job.priority, job.signature) for job in sorted(preparation._QUEUE)],
                         [(0, "signature-one"), (1, "signature-two")])
        self.assertNotIn(("project", "signature-far"), preparation._WORK)

    def test_load_starts_exactly_one_background_work(self) -> None:
        project = {
            "revision": 7,
            "settings": {"lineGap": 0.7},
            "scenes": [
                {"id": "scene", "lines": [_line("one", -0.2), _line("two", 0), _line("three", -0.3), _line("four", 0)]}
            ],
        }
        with (
            patch.object(preparation, "_project_key", return_value="project:7"),
            patch("server.modules.overlap_mix.prepare_overlap_boundaries", return_value=_boundaries("one", "three")),
            patch.object(preparation, "_ensure_worker"),
        ):
            result = preparation.start_overlap_preparation(project)

        self.assertEqual(result["boundaries"], ["one", "three"])
        self.assertEqual(len(preparation._QUEUE), 1)
        self.assertEqual(preparation._QUEUE[0].priority, 10)
        self.assertEqual(preparation._QUEUE[0].signature, "signature-one")
        self.assertEqual(
            [state["status"] for state in preparation._STATE.values()],
            ["queued", "idle"],
        )

    def test_playback_promotes_at_most_two_boundaries_in_requested_order(self) -> None:
        project = {
            "revision": 1,
            "settings": {"lineGap": -0.2},
            "scenes": [
                {
                    "id": "scene",
                    "lines": [_line("one", -0.2), _line("two", -0.2), _line("three", -0.2), _line("four", 0)],
                }
            ],
        }
        with (
            patch.object(preparation, "_project_key", return_value="project:1"),
            patch(
                "server.modules.overlap_mix.prepare_overlap_boundaries", return_value=_boundaries("one", "two", "three")
            ),
            patch.object(preparation, "_ensure_worker"),
        ):
            preparation.start_overlap_preparation(project)
            response = preparation.update_playback("playback", ["two", "one", "three"])

        queued = sorted(preparation._QUEUE)
        self.assertEqual(response["leadingLineIds"], ["two", "one"])
        self.assertEqual(
            [(job.priority, job.signature) for job in queued[:2]], [(0, "signature-two"), (1, "signature-one")]
        )
        self.assertEqual(sum(job.priority < 10 for job in queued), 2)
        self.assertNotIn(("project:1", "signature-one"), preparation._STATE)

    def test_missing_playback_window_interrupts_background_and_deduplicates_work(self) -> None:
        project = {
            "revision": 1,
            "settings": {"lineGap": -0.2},
            "scenes": [{"id": "scene", "lines": [_line("one", -0.2), _line("two", -0.2), _line("three", 0)]}],
        }
        background = preparation._Work("background", "project", "signature-background", "background", {}, 10, {"background"})
        with (
            preparation._CONDITION,
            patch.object(preparation, "_project_key", return_value="project"),
            patch("server.modules.overlap_mix.prepare_overlap_boundaries", return_value=_boundaries("one", "two")),
            patch.object(preparation, "_ensure_worker"),
        ):
            preparation.start_overlap_preparation(project)
            preparation._ACTIVE = background
            preparation.update_playback("playback", ["one", "one", "two"])
            first = preparation._enqueue("project", "one", 0)
            second = preparation._enqueue("project", "one", 0)

            self.assertTrue(background.cancel.is_set())
            self.assertIs(first, second)
            self.assertEqual(preparation._PLAYBACKS["playback"].line_ids, ["one", "two"])

    def test_background_waits_for_announced_ready_window_and_resumes_one_at_a_time(self) -> None:
        boundaries = _boundaries("one", "two", "background", "later")
        preparation._PLANS["project"] = preparation._Plan("project", boundaries)
        preparation._CURRENT_PROJECT_KEY = "project"
        preparation._PLAYBACKS["playback"] = preparation._Playback("project", ["one", "two"], {}, False)
        preparation._ACTIVE_PLAYBACKS["project"] = "playback"
        for line_id in ("one", "two"):
            work = preparation._Work(
                line_id, "project", f"signature-{line_id}", line_id, boundaries[line_id], 0, {line_id}
            )
            work.result = {"signature": work.signature, "audioUrl": f"/media/{line_id}.wav"}
            work.complete.set()
            preparation._WORK[("project", work.signature)] = work
            preparation._STATE[("project", line_id)] = {"leadingLineId": line_id, "status": "ready"}

        with preparation._CONDITION:
            self.assertFalse(preparation._schedule_background("project"))
            preparation._PLAYBACKS["playback"].window_announced = True
            self.assertTrue(preparation._schedule_background("project"))

        self.assertEqual(len(preparation._QUEUE), 1)
        self.assertEqual(preparation._QUEUE[0].signature, "signature-background")

    def test_interrupted_background_does_not_finish_before_playback_window(self) -> None:
        boundaries = _boundaries("background", "one", "two")
        project = {"revision": 1, "scenes": []}
        background_started = Event()
        urgent_complete = Event()
        completed: list[str] = []

        def render(boundary, *, should_cancel):
            line_id = str(boundary["leadingLineId"])
            if line_id == "background" and not background_started.is_set():
                background_started.set()
                deadline = monotonic() + 2
                while not should_cancel() and monotonic() < deadline:
                    sleep(0.001)
                if should_cancel():
                    raise InterruptedError
            completed.append(line_id)
            if {"one", "two"}.issubset(completed):
                urgent_complete.set()
            return {"signature": boundary["signature"], "audioUrl": f"/media/{line_id}.wav"}

        with (
            patch.object(preparation, "_project_key", return_value="project"),
            patch("server.modules.overlap_mix.prepare_overlap_boundaries", return_value=boundaries),
            patch("server.modules.overlap_mix.render_prepared_overlap", side_effect=render),
            self.running_worker(),
        ):
            preparation.start_overlap_preparation(project)
            self.assertTrue(background_started.wait(1))
            preparation.update_playback("playback", ["one", "two"], start=True)
            self.assertTrue(urgent_complete.wait(2))

        self.assertEqual(completed[:2], ["one", "two"])
        self.assertNotIn("background", completed[:2])

    def test_stop_resumes_only_one_background_work(self) -> None:
        boundaries = _boundaries("one", "two", "background", "later")
        preparation._PLANS["project"] = preparation._Plan("project", boundaries)
        preparation._CURRENT_PROJECT_KEY = "project"
        preparation._PLAYBACKS["playback"] = preparation._Playback("project", ["one", "two"], {}, True)
        preparation._ACTIVE_PLAYBACKS["project"] = "playback"
        preparation._STATE[("project", "one")] = {"leadingLineId": "one", "status": "queued"}

        with patch.object(preparation, "_ensure_worker"):
            preparation.stop_playback("playback")

        self.assertEqual(len(preparation._QUEUE), 1)
        self.assertEqual(preparation._QUEUE[0].priority, 10)

    def test_stopped_playback_runs_background_boundaries_sequentially(self) -> None:
        boundaries = _boundaries("background", "later")
        preparation._PLANS["project"] = preparation._Plan("project", boundaries)
        preparation._CURRENT_PROJECT_KEY = "project"
        preparation._PLAYBACKS["playback"] = preparation._Playback("project", ["missing"], {}, True)
        preparation._ACTIVE_PLAYBACKS["project"] = "playback"
        first_started = Event()
        release_first = Event()
        second_started = Event()
        completed = Event()
        calls: list[str] = []

        def render(boundary, **_kwargs):
            line_id = str(boundary["leadingLineId"])
            calls.append(line_id)
            if line_id == "background":
                first_started.set()
                release_first.wait(1)
            else:
                second_started.set()
                completed.set()
            return {"signature": boundary["signature"], "audioUrl": f"/media/{line_id}.wav"}

        with patch("server.modules.overlap_mix.render_prepared_overlap", side_effect=render), self.running_worker():
            preparation.stop_playback("playback")
            self.assertTrue(first_started.wait(1))
            self.assertEqual(calls, ["background"])
            self.assertFalse(second_started.is_set())
            release_first.set()
            self.assertTrue(completed.wait(1))
            preparation._WORK[("project", "signature-later")].complete.wait(1)

        self.assertEqual(calls, ["background", "later"])

    def test_completed_work_is_reused_without_requeueing(self) -> None:
        boundary = _boundaries("one")["one"]
        preparation._PLANS["project"] = preparation._Plan("project", {"one": boundary})
        completed = preparation._Work("request", "project", "signature-one", "one", boundary, 0, {"one"})
        completed.result = {"signature": "cached", "audioUrl": "/media/cached.wav"}
        completed.complete.set()
        preparation._WORK[("project", "signature-one")] = completed

        reused = preparation._enqueue("project", "one", 0)

        self.assertIs(reused, completed)
        self.assertEqual(preparation._QUEUE, [])

    def test_cache_hit_does_not_interrupt_unrelated_background(self) -> None:
        boundary = _boundaries("one")["one"]
        preparation._PLANS["project"] = preparation._Plan("project", {"one": boundary})
        preparation._CURRENT_PROJECT_KEY = "project"
        completed = preparation._Work("request", "project", "signature-one", "one", boundary, 0, {"one"})
        completed.result = {
            "signature": "signature-one",
            "audioUrl": "/media/cached.wav",
            "diagnostics": {"snapshotMs": 0.0, "hashMs": 1.25, "cacheHit": True},
        }
        completed.complete.set()
        preparation._WORK[("project", "signature-one")] = completed
        preparation._STATE[("project", "one")] = {"leadingLineId": "one", "status": "ready"}
        background = preparation._Work("background", "project", "other", "other", {}, 10, {"other"})
        preparation._ACTIVE = background

        result = preparation.request_overlap("one")

        self.assertEqual(result["audioUrl"], "/media/cached.wav")
        self.assertEqual(result["diagnostics"]["snapshotMs"], 0.0)
        self.assertEqual(result["diagnostics"]["hashMs"], 1.25)
        self.assertEqual(result["diagnostics"]["queueWaitMs"], 0.0)
        self.assertFalse(background.cancel.is_set())

    def test_initial_notification_pauses_background_until_full_window_arrives(self) -> None:
        boundaries = _boundaries("one", "background")
        preparation._PLANS["project"] = preparation._Plan("project", boundaries)
        preparation._CURRENT_PROJECT_KEY = "project"
        completed = preparation._Work("request", "project", "signature-one", "one", boundaries["one"], 0, {"one"})
        completed.result = {"signature": "signature-one", "audioUrl": "/media/cached.wav"}
        completed.complete.set()
        preparation._WORK[("project", "signature-one")] = completed
        preparation._STATE[("project", "one")] = {"leadingLineId": "one", "status": "ready"}
        background = preparation._Work("background", "project", "other", "background", {}, 10, {"background"})
        preparation._ACTIVE = background

        with patch.object(preparation, "_ensure_worker"):
            preparation.update_playback("playback", ["one"], start=True)

        self.assertTrue(background.cancel.is_set())
        self.assertFalse(preparation._PLAYBACKS["playback"].window_announced)

    def test_same_signature_shares_one_work(self) -> None:
        boundaries = _boundaries("one", "alias")
        boundaries["alias"]["signature"] = "signature-one"
        preparation._PLANS["project"] = preparation._Plan("project", boundaries)

        first = preparation._enqueue("project", "one", 0)
        second = preparation._enqueue("project", "alias", 1)

        self.assertIs(first, second)
        self.assertEqual(first.line_ids, {"one", "alias"})
        self.assertEqual(len(preparation._QUEUE), 1)

    def test_simultaneous_same_signature_renders_once_without_worker_project_read(self) -> None:
        boundaries = _boundaries("one", "alias")
        boundaries["alias"]["signature"] = "signature-one"
        project = {"revision": 1, "scenes": []}
        render_count = 0

        def render(_boundary, **_kwargs):
            nonlocal render_count
            render_count += 1
            return {"signature": "signature-one", "audioUrl": "/media/cached.wav"}

        with (
            patch.object(preparation, "_project_key", return_value="project"),
            patch("server.modules.overlap_mix.prepare_overlap_boundaries", return_value=boundaries),
            patch("server.modules.overlap_mix.render_prepared_overlap", side_effect=render),
            patch("server.modules.project_repository.read_project") as read_project,
            self.running_worker(),
        ):
            preparation.start_overlap_preparation(project)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(preparation.request_overlap, ("one", "alias")))

        self.assertEqual(render_count, 1)
        self.assertEqual(results[0]["signature"], results[1]["signature"])
        read_project.assert_not_called()

    def test_project_revision_changes_the_work_generation(self) -> None:
        first = preparation._project_key({"revision": 7})
        second = preparation._project_key({"revision": 8})

        self.assertNotEqual(first, second)

    def test_refresh_invalidates_only_changed_signatures_and_keeps_ready_cache(self) -> None:
        old = _boundaries("one", "two", "three")
        new = _boundaries("one", "two", "three")
        new["two"]["signature"] = "changed-two"
        preparation._CURRENT_PROJECT_KEY = "project"
        preparation._PLANS["project"] = preparation._Plan("project", old)
        retained: dict[str, preparation._Work] = {}
        for line_id in ("one", "three"):
            work = preparation._Work(line_id, "project", f"signature-{line_id}", line_id, old[line_id], 10, {line_id})
            work.result = {"signature": work.signature, "audioUrl": f"/media/{line_id}.wav"}
            work.complete.set()
            preparation._WORK[("project", work.signature)] = work
            preparation._STATE[("project", line_id)] = {"leadingLineId": line_id, "status": "ready"}
            retained[line_id] = work
        obsolete = preparation._Work("two", "project", "signature-two", "two", old["two"], 10, {"two"})
        obsolete.result = {"signature": obsolete.signature, "audioUrl": "/media/two.wav"}
        obsolete.complete.set()
        preparation._WORK[("project", obsolete.signature)] = obsolete
        preparation._STATE[("project", "two")] = {"leadingLineId": "two", "status": "ready"}

        with (
            patch("server.modules.overlap_mix.prepare_overlap_boundaries", return_value=new),
            patch.object(preparation, "_ensure_worker"),
        ):
            result = preparation.refresh_overlap_preparation({"revision": 2})

        self.assertEqual(result["changedBoundaryIds"], ["two"])
        self.assertIs(preparation._WORK[("project", "signature-one")], retained["one"])
        self.assertIs(preparation._WORK[("project", "signature-three")], retained["three"])
        self.assertNotIn(("project", "signature-two"), preparation._WORK)
        self.assertEqual(preparation._STATE[("project", "one")]["status"], "ready")
        self.assertEqual(preparation._STATE[("project", "three")]["status"], "ready")
        self.assertEqual(preparation._STATE[("project", "two")]["status"], "queued")
        self.assertEqual([item.signature for item in preparation._QUEUE], ["changed-two"])

    def test_project_generation_change_invalidates_active_playback(self) -> None:
        preparation._CURRENT_PROJECT_KEY = "old"
        preparation._PLAYBACKS["old-playback"] = preparation._Playback("old", ["one"], {})
        preparation._ACTIVE_PLAYBACKS["old"] = "old-playback"
        active = preparation._Work("active", "old", "active-signature", "one", {}, 10, {"one"})
        queued = preparation._Work("queued", "old", "queued-signature", "two", {}, 0, {"two"})
        preparation._ACTIVE = active
        preparation._WORK[("old", "active-signature")] = active
        preparation._WORK[("old", "queued-signature")] = queued
        preparation._QUEUE.append(preparation._Queued(0, 1, "old", "queued-signature", "queued"))
        with (
            patch.object(preparation, "_project_key", return_value="new"),
            patch("server.modules.overlap_mix.prepare_overlap_boundaries", return_value={}),
        ):
            preparation.start_overlap_preparation({"revision": 2})

        self.assertEqual(preparation._PLAYBACKS, {})
        self.assertEqual(preparation._ACTIVE_PLAYBACKS, {})
        self.assertTrue(active.invalidated)
        self.assertTrue(active.cancel.is_set())
        self.assertTrue(queued.invalidated)
        self.assertTrue(queued.complete.is_set())
        self.assertEqual(preparation._QUEUE, [])

    def test_new_playback_invalidates_old_updates_and_records_deadlines(self) -> None:
        boundaries = _boundaries("one", "two")
        preparation._PLANS["project"] = preparation._Plan("project", boundaries)
        preparation._CURRENT_PROJECT_KEY = "project"
        with patch.object(preparation, "_ensure_worker"):
            preparation.update_playback("old", ["one"], {"one": 1_000}, start=True)
            preparation.update_playback("new", ["two"], {"two": 2_000}, start=True)
            stale = preparation.update_playback("old", ["one"], {"one": 3_000})

        self.assertTrue(stale["stale"])
        self.assertEqual(stale["leadingLineIds"], [])
        self.assertNotIn("old", preparation._PLAYBACKS)
        self.assertEqual(preparation._STATE[("project", "two")]["deadlineInMs"], 2_000)
        preparation.stop_playback("old")
        self.assertEqual(preparation._ACTIVE_PLAYBACKS["project"], "new")
        preparation.stop_playback("new")
        self.assertNotIn("project", preparation._ACTIVE_PLAYBACKS)

    def test_derived_mix_requests_do_not_snapshot_undo_history(self) -> None:
        self.assertIsNone(history._scope_for("/api/lines/line-1/overlap-mix", "POST"))
        self.assertIsNone(history._scope_for("/api/scenes/scene-1/lines/line-1/cue-mix", "POST"))


if __name__ == "__main__":
    unittest.main()

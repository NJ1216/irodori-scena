from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import draft_job_state, export_service, job_routes, progress_events, runtime_state, script_assistant_jobs
from server.modules.job_publication import public_job
from server.modules.progress_events import ProgressEventStore, format_sse


class ProgressPublicationTests(unittest.TestCase):
    def test_export_cursor_excludes_acknowledged_lines_before_copying(self):
        class CountedLine(dict):
            copies = 0

            def __deepcopy__(self, memo):
                type(self).copies += 1
                return dict(self)

        acknowledged = [{"version": index, "line": CountedLine(id=f"line-{index}")}
                        for index in range(1, 1001)]
        job = {"id": "cursor", "status": "generating", "updateVersion": 1000, "lineUpdates": acknowledged}
        with runtime_state.EXPORT_JOBS_LOCK:
            snapshot = export_service.public_export_job(job, after_update=1000)
        self.assertEqual(snapshot["lineUpdates"], [])
        self.assertEqual(snapshot["updateVersion"], 1000)
        self.assertEqual(CountedLine.copies, 0)

    def test_export_cursor_preserves_detached_updates_and_full_replay(self):
        job = {"id": "cursor", "status": "generating", "updateVersion": 2,
               "lineUpdates": [{"version": index, "line": {"id": f"line-{index}", "takes": [{"id": "take"}]}}
                               for index in (1, 2)]}
        with runtime_state.EXPORT_JOBS_LOCK:
            full = export_service.public_export_job(job)
            delta = export_service.public_export_job(job, after_update=1)
            empty = export_service.public_export_job(job, after_update=2)
        store = ProgressEventStore()
        replay = store.observe(full)
        before = format_sse(replay)
        self.assertLess(full.version, delta.version)
        self.assertLess(delta.version, empty.version)
        self.assertEqual([update["version"] for update in delta["lineUpdates"]], [2])
        self.assertEqual([update["version"] for update in replay.metrics["lineUpdates"]], [1, 2])
        job["lineUpdates"][1]["line"]["takes"][0]["id"] = "changed"
        self.assertEqual(delta["lineUpdates"][0]["line"]["takes"][0]["id"], "take")
        delta["lineUpdates"][0]["line"]["takes"].clear()
        self.assertEqual(full["lineUpdates"][1]["line"]["takes"], [{"id": "take"}])
        self.assertEqual(format_sse(replay), before)
        self.assertNotIn("_progressVersion", json.dumps(delta))

    def test_nested_job_and_public_values_cannot_change_a_past_sequence(self):
        job = {"id": "immutable", "status": "generating", "chunks": [{"lines": ["original"]}]}
        store = ProgressEventStore()
        event = store.observe(job)
        before = format_sse(event)
        job["chunks"][0]["lines"].append("later")
        event.public()["metrics"]["chunks"][0]["lines"].append("caller mutation")
        event.metrics["chunks"].clear()
        self.assertEqual(format_sse(event), before)

    def test_delayed_publications_cannot_follow_the_terminal_update(self):
        cases = [
            ("DRAFT_JOBS", draft_job_state.update_draft_job, draft_job_state.public_draft_job),
            ("EXPORT_JOBS", export_service.update_export_job, export_service.public_export_job),
            ("SCRIPT_ASSISTANT_JOBS", script_assistant_jobs._update, script_assistant_jobs.public_script_assistant_job),
        ]
        for name, update, snapshot in cases:
            with self.subTest(name=name):
                job = {"id": "ordered", "status": "planning", "chunks": []}
                store = ProgressEventStore()
                delayed = []
                observe = store.observe

                def publish(value):
                    if value["status"] == "generating":
                        delayed.append(value)
                    else:
                        observe(value)

                with patch.object(runtime_state, name, {job["id"]: job}), patch.object(
                    progress_events, "PROGRESS_EVENTS", store,
                ), patch.object(store, "observe", side_effect=publish):
                    update(job["id"], status="generating")
                    update(job["id"], status="completed")
                observe(delayed[0])
                events = store.after(job["id"], 0)
                self.assertEqual([event.metrics["status"] for event in events], ["completed"])
                self.assertEqual(events[-1].metrics["chunks"], snapshot(job)["chunks"])

    def test_snapshot_excludes_private_payload_before_copying(self):
        class PrivateValue:
            def __deepcopy__(self, memo):
                raise AssertionError("private payload must not be copied")

        job = {"id": "public", "status": "generating", "sourceProject": PrivateValue(),
               "request": PrivateValue(), "chunks": [{"index": 1}]}
        snapshot = script_assistant_jobs.public_script_assistant_job(job)
        job["chunks"].append({"index": 2})
        self.assertEqual(snapshot["chunks"], [{"index": 1}])
        self.assertEqual(set(json.loads(json.dumps(snapshot))), {"id", "status", "chunks"})

    def test_identical_newer_snapshot_still_rejects_a_delayed_older_one(self):
        job = {"id": "dedupe", "status": "generating"}
        store = ProgressEventStore()
        first = public_job(job, set())
        store.observe(first)
        job["status"] = "writing"
        delayed = public_job(job, set())
        job["status"] = "generating"
        self.assertIsNone(store.observe(public_job(job, set())))
        self.assertIsNone(store.observe(delayed))
        self.assertEqual(len(store.after(job["id"], 0)), 1)

    def test_export_cancel_get_and_sse_use_the_same_public_boundary(self):
        job = {"id": "export_job_ordered", "status": "generating", "lineUpdates": [], "completedLines": 0, "totalLines": 1}
        store = ProgressEventStore()
        with patch.object(runtime_state, "EXPORT_JOBS", {job["id"]: job}), patch.object(progress_events, "PROGRESS_EVENTS", store):
            cancelled = job_routes.cancel_export_job(job["id"])
            self.assertTrue(cancelled["cancelRequested"])
            export_service.update_export_job(job["id"], status="cancelled", completedAt=1)
            with patch("server.modules.job_retention.evict_terminal_jobs"):
                final = job_routes.get_export_job(job["id"])
                frames = list(progress_events.stream_progress(job_routes.get_export_job, job["id"]))
            self.assertEqual(store.after(job["id"], 0)[-1].metrics["status"], final["status"])
            self.assertIn('"terminal":true', frames[-1])
            self.assertNotIn("_progressVersion", json.dumps(final))

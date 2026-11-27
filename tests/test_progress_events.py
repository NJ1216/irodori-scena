from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import threading
import time
import unittest
from unittest.mock import patch

from server.modules import progress_events
from server.modules.progress_events import ProgressEventStore, format_sse


class ProgressEventStoreTests(unittest.TestCase):
    def test_stream_reconciles_unpublished_completion_after_idle_wait(self) -> None:
        job = {"id": "missed_completion", "status": "generating"}
        store = ProgressEventStore()
        with patch.object(progress_events, "PROGRESS_EVENTS", store):
            stream = progress_events.stream_progress(lambda _: dict(job), job["id"])
            next(stream)
            job["status"] = "completed"
            with patch.object(store, "wait_after", return_value=[]):
                self.assertIn('"terminal":true', next(stream))
            with self.assertRaises(StopIteration):
                next(stream)

    def test_warning_completion_is_terminal(self) -> None:
        store = ProgressEventStore()
        self.assertTrue(store.observe({"id": "warnings", "status": "completed_with_warnings"}).terminal)

    def test_observe_deduplicates_and_sequences_changes(self) -> None:
        store = ProgressEventStore()
        job = {"id": "ai_job_1", "status": "generating", "phase": "dialogue",
               "overallProgress": 25, "receivedRecords": 2}
        first = store.observe(job)
        self.assertIsNotNone(first)
        self.assertIsNone(store.observe(dict(job)))
        second = store.observe({**job, "overallProgress": 50})
        self.assertEqual([event.sequence for event in store.after(job["id"], 0)], [1, 2])
        self.assertEqual(second.current, 50)
        self.assertEqual(second.total, 100)

    def test_terminal_event_and_sse_wire_shape(self) -> None:
        store = ProgressEventStore()
        event = store.observe({"id": "export_job_1", "status": "completed",
                               "completedLines": 3, "totalLines": 3})
        self.assertTrue(event.terminal)
        frame = format_sse(event)
        payload = json.loads(next(line[6:] for line in frame.splitlines() if line.startswith("data: ")))
        self.assertEqual(payload["jobId"], "export_job_1")
        self.assertEqual(set(payload), {"sequence", "jobId", "phase", "current", "total",
                                        "metrics", "timestamp", "terminal"})

    def test_export_alignment_progress_uses_its_own_line_counts(self) -> None:
        event = ProgressEventStore().observe({
            "id": "lab_export", "status": "aligning",
            "completedLines": 34, "totalLines": 34,
            "alignmentCompletedLines": 12, "alignmentTotalLines": 34,
        })
        self.assertEqual((event.current, event.total), (12, 34))

    def test_wait_after_wakes_for_new_event(self) -> None:
        store = ProgressEventStore()
        received = []
        waiter = threading.Thread(target=lambda: received.extend(store.wait_after("job_1", 0, 1)))
        waiter.start()
        time.sleep(0.01)
        store.observe({"id": "job_1", "status": "generating"})
        waiter.join(timeout=1)
        self.assertEqual([event.sequence for event in received], [1])

    def test_retention_keeps_newest_events(self) -> None:
        store = ProgressEventStore(max_events=2)
        for current in range(3):
            store.observe({"id": "job_1", "status": "generating", "completedLines": current,
                           "totalLines": 3})
        self.assertEqual([event.sequence for event in store.after("job_1", 0)], [2, 3])

    def test_stream_wakes_when_terminal_mutation_is_published(self) -> None:
        job = {"id": "latency_job", "status": "generating", "completedLines": 0, "totalLines": 1}
        stream = progress_events.stream_progress(lambda _job_id: dict(job), job["id"])
        self.assertIn('"sequence":1', next(stream))
        job.update(status="cancelled", completedLines=1)
        progress_events.PROGRESS_EVENTS.observe(dict(job))
        started = time.perf_counter()
        terminal = next(stream)
        self.assertLess(time.perf_counter() - started, 0.25)
        self.assertIn('"terminal":true', terminal)
        with self.assertRaises(StopIteration):
            next(stream)


if __name__ == "__main__":
    unittest.main()

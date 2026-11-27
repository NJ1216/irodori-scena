import scena_test_isolation  # noqa: F401
import unittest

from server.modules.progress_events import ProgressEventStore


class ProgressReplayBudgetTests(unittest.TestCase):
    def test_bounds_utf8_history_without_altering_latest_progress(self):
        store = ProgressEventStore(max_bytes=4000)
        job = {"id": "large", "status": "generating", "completedLines": 0,
               "totalLines": 6, "lineUpdates": []}
        for current in range(1, 7):
            job.update(completedLines=current, lineUpdates=[{"text": "日本語" * 80}] * current)
            latest = store.observe(job)
            events = store.after(job["id"], 0)
            self.assertLessEqual(sum(len(event.body.encode("utf-8")) for event in events),
                                 max(4000, len(latest.body.encode("utf-8"))))
            self.assertEqual(events[-1].metrics["lineUpdates"], job["lineUpdates"])
            self.assertEqual((events[-1].current, events[-1].total), (current, 6))
        self.assertGreater(store.after(job["id"], 0)[0].sequence, 1)
        self.assertIsNone(store.observe(dict(job)))

    def test_retains_oversized_terminal_and_resets_accounting_on_discard(self):
        store = ProgressEventStore(max_bytes=300)
        store.observe({"id": "job", "status": "generating"})
        terminal = store.observe({"id": "job", "status": "completed", "lineUpdates": ["音声" * 3000]})
        self.assertEqual(store.wait_after("job", 0, 0), [terminal])
        self.assertTrue(terminal.terminal)
        self.assertEqual(terminal.sequence, 2)
        store.discard("job")
        self.assertEqual(store.after("job", 0), [])
        restarted = store.observe({"id": "job", "status": "generating"})
        self.assertEqual(restarted.sequence, 1)
        self.assertEqual(store.after("job", 0), [restarted])

    def test_budget_is_independent_for_each_job_and_count_still_applies(self):
        store = ProgressEventStore(max_events=2, max_bytes=4000)
        for current in range(5):
            store.observe({"id": "small", "status": "generating", "completedLines": current})
            store.observe({"id": "large", "status": "generating", "lineUpdates": ["x" * 5000],
                           "completedLines": current})
        self.assertEqual([event.sequence for event in store.after("small", 0)], [4, 5])
        self.assertEqual([event.sequence for event in store.after("large", 0)], [5])

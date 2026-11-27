from __future__ import annotations

import scena_test_isolation  # noqa: F401
import threading
import unittest

from fastapi import HTTPException

from server.app import PROGRESS_EVENTS
from server.modules import job_retention
from server.modules.runtime_state import SCRIPT_ASSISTANT_JOBS_LOCK, SCRIPT_ASSISTANT_PROPOSALS


class JobRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        job_retention.reset_expired_tombstones()
        with SCRIPT_ASSISTANT_JOBS_LOCK:
            SCRIPT_ASSISTANT_PROPOSALS.clear()

    def test_ttl_evicts_terminal_job_and_all_progress_state(self) -> None:
        jobs = {"expired": {"id": "expired", "status": "completed", "completedAt": 1}}
        PROGRESS_EVENTS.observe(jobs["expired"])
        self.assertEqual(job_retention.evict_terminal_jobs(
            jobs, threading.RLock(), now_ms=job_retention.JOB_TTL_MS + 1), ["expired"])
        self.assertNotIn("expired", jobs)
        self.assertEqual(PROGRESS_EVENTS.after("expired", 0), [])
        with self.assertRaises(HTTPException) as raised:
            job_retention.raise_missing("expired", "missing")
        self.assertEqual(raised.exception.status_code, 410)

    def test_running_jobs_are_never_evicted_and_unknown_id_is_404(self) -> None:
        jobs = {f"job-{index}": {"id": f"job-{index}", "status": "generating", "startedAt": 1}
                for index in range(job_retention.JOB_LIMIT + 20)}
        self.assertEqual(job_retention.evict_terminal_jobs(
            jobs, threading.RLock(), now_ms=job_retention.JOB_TTL_MS * 2), [])
        self.assertEqual(len(jobs), job_retention.JOB_LIMIT + 20)
        with self.assertRaises(HTTPException) as raised:
            job_retention.raise_missing("never-seen", "missing")
        self.assertEqual(raised.exception.status_code, 404)

    def test_warning_completion_is_retained_as_a_terminal_job(self) -> None:
        jobs = {"warnings": {"id": "warnings", "status": "completed_with_warnings", "completedAt": 1}}
        self.assertEqual(job_retention.evict_terminal_jobs(
            jobs, threading.RLock(), now_ms=job_retention.JOB_TTL_MS + 1), ["warnings"])

    def test_proposal_retention_uses_ttl_and_count_limit(self) -> None:
        with SCRIPT_ASSISTANT_JOBS_LOCK:
            for index in range(job_retention.PROPOSAL_LIMIT + 2):
                identifier = f"proposal-{index}"
                SCRIPT_ASSISTANT_PROPOSALS[identifier] = {"id": identifier, "createdAt": index + 1}
        removed = job_retention.evict_script_assistant_proposals(now_ms=job_retention.JOB_TTL_MS + 2)
        self.assertIn("proposal-0", removed)
        self.assertIn("proposal-1", removed)
        self.assertLessEqual(len(SCRIPT_ASSISTANT_PROPOSALS), job_retention.PROPOSAL_LIMIT)


if __name__ == "__main__":
    unittest.main()

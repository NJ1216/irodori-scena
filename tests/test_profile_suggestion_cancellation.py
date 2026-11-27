from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest

from fastapi import HTTPException

from server.app import PROFILE_SUGGESTION_JOBS, PROFILE_SUGGESTION_JOBS_LOCK
from server.modules.profile_suggestion_routes import cancel_profile_suggestion_job


class ProfileSuggestionCancellationTests(unittest.TestCase):
    def test_running_job_can_be_cancelled(self) -> None:
        job_id = "profile-cancel-test"
        with PROFILE_SUGGESTION_JOBS_LOCK:
            PROFILE_SUGGESTION_JOBS[job_id] = {
                "id": job_id, "status": "generating", "phase": "profile",
                "message": "生成中", "completedRelations": 0, "totalRelations": 1,
                "cancelRequested": False,
            }
        try:
            result = cancel_profile_suggestion_job(job_id)
            self.assertEqual(result["status"], "cancelled")
            self.assertTrue(result["cancelRequested"])
            with self.assertRaises(HTTPException) as error:
                cancel_profile_suggestion_job(job_id)
            self.assertEqual(error.exception.status_code, 409)
        finally:
            with PROFILE_SUGGESTION_JOBS_LOCK:
                PROFILE_SUGGESTION_JOBS.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules.draft_stream_progress import draft_stream_progress_reporter


class DraftStreamProgressTests(unittest.TestCase):
    def test_unverified_repeated_stream_never_inflates_confirmed_characters(self):
        updates: list[dict] = []
        advances: list[dict] = []
        repeated = '{"text":"' + ("繰り返しの台詞です。" * 310) + '"}'
        with patch("server.modules.draft_stream_progress.time.monotonic", side_effect=[1.0, 3.0]), \
             patch("server.modules.draft_job_state.update_draft_job", side_effect=lambda _id, **value: updates.append(value)), \
             patch("server.modules.draft_job_state.advance_draft_progress", side_effect=lambda _id, **value: advances.append(value)):
            report = draft_stream_progress_reporter("job", 227, {"cast": "A"}, 3_000)
            report(repeated)
            report(repeated + repeated)
        self.assertEqual([item["generated_characters"] for item in advances], [227, 227])
        self.assertTrue(all("overall_progress" not in item for item in advances))
        self.assertGreater(updates[1]["estimatedGeneratedCharacters"], updates[0]["estimatedGeneratedCharacters"])
        self.assertTrue(all(item["message"] == "応答を確認中" for item in updates))


if __name__ == "__main__":
    unittest.main()

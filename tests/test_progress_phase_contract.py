from __future__ import annotations

import scena_test_isolation  # noqa: F401
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.app import app as _registered_app  # noqa: F401
from server.modules import export_service, job_routes, progress_events, runtime_state
from server.modules.progress_events import ProgressEventStore


class ProgressPhaseContractTests(unittest.TestCase):
    def test_inactive_alignment_counters_do_not_hide_export_progress(self) -> None:
        for status in ["preparing", "generating", "writing", "completed"]:
            with self.subTest(status=status):
                event = ProgressEventStore().observe({
                    "id": "export", "status": status, "phase": status,
                    "completedLines": 2, "totalLines": 5,
                    "alignmentCompletedLines": 0, "alignmentTotalLines": 0,
                })
                self.assertEqual((event.current, event.total), (2, 5))

    def test_direction_uses_applied_performance_lines(self) -> None:
        job = job_routes._new_direction_job("direction", SimpleNamespace(line_ids=["a", "b", "c"]))
        job.update(status="generating", phase="direction", performanceCompletedLines=2)
        event = ProgressEventStore().observe(job)
        self.assertEqual((event.current, event.total), (2, 3))
        self.assertEqual(event.metrics["performanceCompletedLines"], 2)

    def test_active_alignment_uses_its_counts_even_when_the_total_is_unknown(self) -> None:
        for total in [0, 5]:
            with self.subTest(total=total):
                event = ProgressEventStore().observe({
                    "id": "alignment", "status": "aligning", "phase": "aligning",
                    "completedLines": 5, "totalLines": 5,
                    "alignmentCompletedLines": 0, "alignmentTotalLines": total,
                })
                self.assertEqual((event.current, event.total), (0, total))

    def test_overall_percentage_keeps_precedence_for_drafts(self) -> None:
        event = ProgressEventStore().observe({
            "id": "draft", "status": "generating", "phase": "dialogue",
            "overallProgress": 42, "performanceCompletedLines": 0, "performanceTotalLines": 0,
            "completedChunks": 1, "totalChunks": 3,
        })
        self.assertEqual((event.current, event.total), (42, 100))

    def test_prepare_job_publishes_generation_and_completion_phases_with_line_updates(self) -> None:
        line = {"id": "line", "text": "台詞", "takes": [{"id": "take"}], "selectedTakeId": "take"}
        scene = {"id": "scene", "lines": [line]}
        project = {"settings": {}, "scenes": [scene]}
        job = {"id": "export", "mode": "prepare", "status": "preparing", "phase": "preparing", "alignmentCompletedLines": 0, "alignmentTotalLines": 0}
        store = ProgressEventStore()
        with (
            patch.object(runtime_state, "EXPORT_JOBS", {job["id"]: job}),
            patch.object(progress_events, "PROGRESS_EVENTS", store),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch.object(export_service, "selected_take_is_available", return_value=False),
            patch.object(export_service, "ensure_export_take", return_value=(project, scene, line, True)),
        ):
            export_service.run_export_job(job["id"])
        events = store.after(job["id"], 0)
        self.assertEqual(events[0].phase, "generating")
        self.assertEqual((events[0].current, events[0].total), (0, 1))
        self.assertEqual(events[-1].phase, "completed")
        self.assertEqual((events[-1].current, events[-1].total), (1, 1))
        self.assertEqual(sum(event.terminal for event in events), 1)
        self.assertEqual(events[-1].metrics["lineUpdates"][0]["line"]["selectedTakeId"], "take")


if __name__ == "__main__":
    unittest.main()

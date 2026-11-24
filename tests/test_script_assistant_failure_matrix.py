from __future__ import annotations

import random
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from server.app import app as _app  # noqa: F401
from server.modules.script_assistant_jobs import run_script_assistant_job
from server.modules.script_assistant_models import ScriptAssistantRequest
from server.modules.runtime_state import SCRIPT_ASSISTANT_JOBS, SCRIPT_ASSISTANT_PROPOSALS


def _line(line_id: str, speaker: str, text: str) -> dict:
    return {"id": line_id, "characterId": speaker, "text": text, "stageDirection": "", "takes": []}


def _project(*scenes: dict, cast_count: int = 2) -> dict:
    return {
        "title": "matrix",
        "characters": [
            {"id": f"cast-{index}", "name": f"話者{index}", "profile": "設定" * (index + 1)}
            for index in range(cast_count)
        ],
        "settings": {"speechRate": 1.2, "lineGap": 0.7},
        "scenes": list(scenes),
    }


def _request(operation: str, line_ids: list[str]) -> ScriptAssistantRequest:
    return ScriptAssistantRequest(
        operation=operation, line_ids=line_ids, character_ids=["cast-0", "cast-1"],
        target_line_count=len(line_ids), base_url="http://127.0.0.1:9999/v1", model="scripted",
    )


class ScriptAssistantFailureMatrixTests(TestCase):
    def setUp(self) -> None:
        SCRIPT_ASSISTANT_JOBS.clear()
        SCRIPT_ASSISTANT_PROPOSALS.clear()

    def _run(self, job_id: str, request: ScriptAssistantRequest, project: dict, responses) -> dict:
        SCRIPT_ASSISTANT_JOBS[job_id] = {
            "id": job_id, "status": "planning", "cancelRequested": False,
        }
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-matrix")),
            patch("server.modules.draft_capability.build_direction_capability_profile", return_value={
                "provider": "openai", "contextCeiling": 32768, "effectiveContext": 32768,
            }),
            patch("server.modules.script_assistant_jobs._call", side_effect=responses),
        ):
            run_script_assistant_job(job_id, request, project)
        return SCRIPT_ASSISTANT_JOBS[job_id]

    def test_later_scene_failure_keeps_the_earlier_usable_proposal(self) -> None:
        project = _project(
            {"id": "one", "title": "一", "lines": [_line("one-line", "cast-0", "元一")]},
            {"id": "two", "title": "二", "lines": [_line("two-line", "cast-1", "元二")]},
        )
        job = self._run("partial-scenes", _request("paraphrase", ["one-line", "two-line"]), project, [
            "R1|A|利用できる提案", RuntimeError("scripted transport failure"),
        ])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["groups"]), 1)
        self.assertEqual(job["groups"][0]["rows"][0]["originalLineId"], "one-line")
        self.assertIn("2/2 シーン目", job["warnings"][-1])
        self.assertIn("一部", job["message"])

    def test_duplicate_and_out_of_order_paraphrases_keep_first_valid_sibling_in_source_order(self) -> None:
        project = _project({"id": "scene", "title": "一", "lines": [
            _line("first", "cast-0", "元一"), _line("second", "cast-1", "元二"),
        ]})
        response = "\n".join([
            "R2|B|二つ目", "R1|A|最初の有効値", "R1|A|重複した値", "R9|A|不明行", "Z|不明話者",
        ])
        job = self._run("records", _request("paraphrase", ["first", "second"]), project, [response])
        rows = job["groups"][0]["rows"]
        self.assertEqual([(row["originalLineId"], row["text"]) for row in rows], [
            ("first", "最初の有効値"), ("second", "二つ目"),
        ])

    def test_fixed_seed_selection_and_truncation_matrix_preserves_addressable_rows(self) -> None:
        rng = random.Random(42)
        for size in (1, 100):
            lines = [_line(f"line-{index}", f"cast-{index % 2}", f"元{index}") for index in range(size)]
            selected = sorted(rng.sample(range(size), k=max(1, size // 5)))
            ids = [f"line-{index}" for index in selected]
            records = [f"R{index + 1}|{'A' if source % 2 == 0 else 'B'}|提案{source}" for index, source in enumerate(selected)]
            if len(records) > 1:
                records.pop(len(records) // 2)  # deterministic truncated sibling
            project = _project({"id": "scene", "title": "一", "lines": lines})
            job = self._run(
                f"seed-{size}", _request("paraphrase", ids), project,
                ["\n".join(reversed(records)), ""],
            )
            rows = job["groups"][0]["rows"]
            self.assertTrue(rows)
            self.assertEqual(len({row["originalLineId"] for row in rows}), len(rows))
            self.assertTrue({row["originalLineId"] for row in rows}.issubset(set(ids)))

    def test_later_interval_transport_failure_keeps_rows_from_the_first_interval(self) -> None:
        lines = [_line(f"line-{index}", f"cast-{index % 2}", f"元{index}") for index in range(100)]
        project = _project({"id": "scene", "title": "一", "lines": lines})
        ids = [line["id"] for line in lines]
        first_batch = "\n".join(
            f"R{index + 1}|{'A' if index % 2 == 0 else 'B'}|提案{index}" for index in range(10)
        )
        job = self._run("partial-interval", _request("paraphrase", ids), project, [
            first_batch, RuntimeError("scripted interval failure"),
        ])
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["groups"][0]["rows"]), 10)
        self.assertIn("部分提案", job["groups"][0]["warnings"][-1])

    def test_cancel_after_last_completion_does_not_publish_a_proposal(self) -> None:
        project = _project({"id": "scene", "title": "一", "lines": [_line("target", "cast-0", "元")]})

        def response(*_args, **_kwargs):
            SCRIPT_ASSISTANT_JOBS["cancel-boundary"]["cancelRequested"] = True
            return "R1|A|生成済み"

        job = self._run("cancel-boundary", _request("paraphrase", ["target"]), project, response)
        self.assertEqual(job["status"], "cancelled")
        self.assertNotIn("proposalId", job)
        self.assertFalse(SCRIPT_ASSISTANT_PROPOSALS)

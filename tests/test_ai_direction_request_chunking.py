from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import AiDirectionRequest, DRAFT_JOBS, DRAFT_JOBS_LOCK, run_ai_direction


def request(**changes: object) -> AiDirectionRequest:
    values = {"base_url": "http://127.0.0.1:11434/v1", "model": "test-model", "line_ids": ["line-1"],
              "emoji_expressions": False, "speech_rate": False, "gap_seconds": False,
              "stage_direction": False, **changes}
    return AiDirectionRequest(**values)


class AiDirectionRequestChunkingTests(unittest.TestCase):
    def test_uses_thirty_line_chunks_with_three_lines_of_context(self) -> None:
        lines = [{"id": f"line-{index}", "characterId": "cast-1", "text": f"発話 {index}", "takes": []}
                 for index in range(1, 68)]
        project = {"scenes": [{"lines": lines}], "characters": [{"id": "cast-1", "name": "彩"}]}
        job_id, calls = "ai_direction_chunk_test", []

        def completion(*_args, **kwargs):
            calls.append(kwargs)
            sections = {key: value for section in kwargs["user"]["sections"] for key, value in section.items()}
            targets = [line for line in sections["lines"].splitlines() if line.startswith("変更対象")]
            return "\n".join(f"{line.split('|')[1]}|direction=自然に話す" for line in targets)

        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (patch("server.modules.project_repository.read_project", return_value=project),
                  patch("server.modules.project_repository.write_project"),
                  patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                  patch("server.modules.llm_client.openai_stream_text_completion", side_effect=completion)):
                run_ai_direction(job_id, request(line_ids=[f"line-{index}" for index in range(4, 65)],
                                                  stage_direction=True))
            self.assertEqual(len(calls), 3)
            prompts = [{key: value for section in call["user"]["sections"] for key, value in section.items()}["lines"]
                       for call in calls]
            first, second, third = prompts
            self.assertEqual(tuple(prompt.count("変更対象") for prompt in prompts), (30, 30, 1))
            self.assertEqual((first.count("変更不可の直前文脈"), first.count("変更不可の直後文脈")), (3, 3))
            self.assertEqual((second.count("変更不可の直前文脈"), second.count("変更不可の直後文脈")), (3, 3))
            self.assertEqual((third.count("変更不可の直前文脈"), third.count("変更不可の直後文脈")), (3, 3))
            self.assertEqual(second.count("既存ト書き=自然に話す"), 3)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_accepts_present_rows_without_retrying_missing_rows(self) -> None:
        lines = [{"id": "line-1", "characterId": "cast-1", "text": "一行目です。", "takes": []},
                 {"id": "line-2", "characterId": "cast-1", "text": "二行目です。", "takes": []}]
        project = {"scenes": [{"lines": lines}], "characters": [{"id": "cast-1", "name": "彩"}]}
        job_id, calls = "ai_direction_targeted_retry_test", []

        def completion(*_args, **kwargs):
            calls.append(kwargs)
            return "L1|direction=自然に話す"

        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (patch("server.modules.project_repository.read_project", return_value=project),
                  patch("server.modules.project_repository.write_project"),
                  patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                  patch("server.modules.llm_client.openai_stream_text_completion", side_effect=completion)):
                run_ai_direction(job_id, request(line_ids=["line-1", "line-2"], stage_direction=True))
            self.assertEqual(len(calls), 1)
            sections = {key: value for section in calls[0]["user"]["sections"] for key, value in section.items()}
            self.assertEqual(sections["lines"].count("変更対象"), 2)
            self.assertEqual(lines[0]["stageDirection"], "自然に話す")
            self.assertNotIn("stageDirection", lines[1])
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

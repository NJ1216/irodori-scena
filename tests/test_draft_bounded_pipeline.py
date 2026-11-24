"""Exercise planning, dialogue parsing, usage and save with a fake HTTP server."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from server.registry import deps


class BoundedPipelineTests(unittest.TestCase):
    def test_legacy_draft_uses_one_scene_per_request_within_finite_budget(self):
        request = deps.DraftRequest(base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            provider="openai", model="models/gemini-3.5-flash", character_ids=["a", "b"],
            target_minutes=3, theme="自己紹介")
        characters = [{"id": identity, "name": name, "profileDetails": {}}
                      for identity, name in (("a", "彩"), ("b", "莉里"))]
        job_id = "bounded-pipeline-test"
        deps.DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "startedAt": 0,
            "cancelRequested": False, "chunks": [], "appendedLines": 0, "estimatedSeconds": 0}
        sent = []

        def post(_endpoint, *, body, **_kwargs):
            payload = json.loads(body)
            sent.append(payload)
            if len(sent) == 1:
                content = "TITLE|自己紹介\nCHAPTER|1|出会い\nOBJECTIVE|互いを知る\nBEAT|名前を紹介する\nBEAT|好きなことを話す\nBEAT|次の約束をする\nEND_CHAPTER"
            else:
                user = json.loads(payload["messages"][1]["content"])
                settings = next(section["accepted_dialogue_and_current_request"]
                                for section in user["sections"] if "accepted_dialogue_and_current_request" in section)
                rows = []
                for source, count in settings["source_target_characters"].items():
                    # Unique fixture sentences avoid the repeated-output guard.
                    offset = sum((index + 1) * ord(char) for index, char in enumerate(source)) * 300
                    text = "自己紹介です。" + "".join(chr(0x4E00 + (offset + index) % 20000)
                                                        for index in range(max(0, count - 7)))
                    rows.extend([f"::SOURCE|{source}",
                        f"NORMAL|{'A' if len(rows) % 2 == 0 else 'B'}|{text}||rate=1.00|gap=0.70|direction=自然に",
                        f"::SOURCE_END|{source}"])
                content = "\n".join(rows)
            usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
            if payload["stream"]:
                event = {"choices": [{"delta": {"content": content}, "finish_reason": "stop"}], "usage": usage}
                raw = f"data: {json.dumps(event)}\n\ndata: [DONE]\n\n".encode()
            else:
                raw = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                  "usage": usage}).encode()
            response = io.BytesIO(raw)
            response.status = 200
            response.headers = {"content-type": "text/event-stream" if payload["stream"] else "application/json"}
            return Mock(), response

        try:
            with tempfile.TemporaryDirectory() as directory, \
                 patch("server.modules.workspace.draft_debug_directory", return_value=Path(directory)), \
                 patch("server.modules.common.openai_http_post", side_effect=post), \
                 patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value={}), \
                 patch("server.modules.llm_registry_metadata.record_llm_usage"), \
                 patch("server.modules.workspace.record_draft_yield", return_value=1.0), \
                 patch("server.modules.project_repository.read_project", return_value={"title": "", "scenes": []}), \
                 patch("server.modules.project_repository.write_project") as save:
                deps.run_draft_job(job_id, request, characters)
            job = deps.DRAFT_JOBS[job_id]
            self.assertEqual(job["status"], "completed", job)
            self.assertEqual(len(sent), 4, job)
            self.assertEqual(job["llmCallCount"], 4)
            self.assertEqual(job["transportCallCount"], 4)
            self.assertLessEqual(job["dialogueAttempt"], job["plannedDialogueCalls"])
            self.assertEqual(job["completedDevelopments"], job["plannedDevelopments"], job.get("dialogueBatchHistory"))
            self.assertGreater(job["appendedLines"], 0)
            self.assertTrue(save.called)
            self.assertEqual(job["tokenUsage"]["inputTokens"], 400)
        finally:
            deps.DRAFT_JOBS.pop(job_id, None)

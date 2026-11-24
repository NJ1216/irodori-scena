from __future__ import annotations

import itertools
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import (
    DRAFT_JOBS,
    DRAFT_JOBS_LOCK,
    DRAFT_LLM_RESPONSES,
    DRAFT_LLM_RESPONSES_LOCK,
    DRAFT_LLM_THREAD_CONTEXT,
    DraftRequest,
    GenerationCancelled,
    active_draft_job,
    cancel_draft_job,
    openai_json_completion,
    require_tts_available,
    run_draft_job,
)
from server.modules import export_service


class DraftCancellationTests(unittest.TestCase):
    def test_tts_allows_the_ai_direction_job_that_owns_the_render(self) -> None:
        job_id = "ai_direction_render_owner_test"
        other_job_id = "draft_job_other_render_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "generating"}
        try:
            self.assertFalse(active_draft_job(excluding_job_id=job_id))
            original_deps = export_service.deps

            class DependencyProxy:
                def selected_tts_runtime(self):
                    return {"engine": {}, "model": {}}

                def __getattr__(self, name):
                    return getattr(original_deps, name)

            dependency_proxy = DependencyProxy()
            with patch.object(export_service, "deps", dependency_proxy):
                require_tts_available(excluding_draft_job_id=job_id)
                with DRAFT_JOBS_LOCK:
                    DRAFT_JOBS[other_job_id] = {"id": other_job_id, "status": "generating"}
                with self.assertRaises(HTTPException) as error:
                    require_tts_available(excluding_draft_job_id=job_id)
            self.assertEqual(error.exception.status_code, 409)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)
                DRAFT_JOBS.pop(other_job_id, None)

    def test_cancellation_removes_directed_chapters_and_skips_inflight_chapter(self) -> None:
        job_id = "draft_job_partial_cancel_test"
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="キャンセル保持を確認するテストテーマです。",
        )
        characters = [{"id": "cast-a", "name": "A", "profileDetails": {}}]
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "planning",
                "cancelRequested": False,
                "overallProgress": 0.0,
                "generatedCharacters": 0,
                "chunks": [],
                "appendedLines": 0,
                "estimatedSeconds": 0,
            }

        dialogue_number = itertools.count(1)

        def fake_dialogue(*_args, **_kwargs):
            number = next(dialogue_number)
            text = "会話を進めます。"
            return (
                {
                    "lines": [
                        {
                            "character_id": "A",
                            "text": f"第{number}章の台詞。{text}",
                            "development_id": source,
                            "source_complete": True,
                        } for source in _kwargs["source_targets"]
                    ]
                },
                None,
            )

        def fake_performance(*_args, **kwargs):
            chapter_index = kwargs["chapter_index"]
            if chapter_index == 1:
                with DRAFT_JOBS_LOCK:
                    DRAFT_JOBS[job_id]["cancelRequested"] = True
            return [
                {
                    "id": f"scene-{chapter_index}",
                    "title": f"第{chapter_index + 1}章",
                    "lines": [
                        {
                            "id": f"line-{chapter_index}",
                            "characterId": "cast-a",
                            "text": "確定済み台詞",
                            "stageDirection": "自然に話す",
                            "speechRate": 1.0,
                            "gapSeconds": 0.7,
                            "takes": [],
                            "selectedTakeId": None,
                        }
                    ],
                }
            ]

        plan = {
            "title": "テスト台本",
            "chapters": [{"title": "前半"}, {"title": "後半"}],
        }
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp")),
            patch("server.modules.draft_algorithms.safe_draft_chapter_characters", return_value=100),
            patch("server.modules.draft_planning.select_draft_optional_context", return_value={"cast-a": set()}),
            patch("server.modules.draft_planning.create_draft_plan", autospec=True, return_value=plan),
            patch("server.modules.draft_dialogue.generate_draft_dialogue", side_effect=fake_dialogue),
            patch("server.modules.draft_algorithms.has_excessive_draft_repetition", return_value=False),
            patch(
                "server.modules.draft_algorithms.remove_repeated_draft_dialogue",
                side_effect=lambda dialogue, _prior: (dialogue, 0),
            ),
            patch("server.modules.draft_performance.direct_draft_performance", side_effect=fake_performance),
            patch("server.modules.project_repository.read_project", return_value={"title": "", "scenes": []}),
            patch("server.modules.project_repository.write_project") as write_project,
        ):
            run_draft_job(job_id, request, characters)

        try:
            with DRAFT_JOBS_LOCK:
                job = DRAFT_JOBS[job_id]
                self.assertEqual(job["status"], "cancelled", job)
                self.assertEqual(job["completedChunks"], 0)
                self.assertEqual(job["appendedLines"], 0)
            self.assertEqual(write_project.call_count, 0)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_cancellation_closes_the_active_llm_response(self) -> None:
        job_id = "draft_job_close_response_test"

        class FakeResponse:
            closed = False

            def close(self) -> None:
                self.closed = True

        response = FakeResponse()
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "generating",
                "cancelRequested": False,
            }
        with DRAFT_LLM_RESPONSES_LOCK:
            DRAFT_LLM_RESPONSES[job_id] = response
        try:
            result = cancel_draft_job(job_id)
            self.assertTrue(result["cancelRequested"])
            self.assertTrue(response.closed)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)
            with DRAFT_LLM_RESPONSES_LOCK:
                DRAFT_LLM_RESPONSES.pop(job_id, None)

    def test_cancellation_closes_connection_while_waiting_for_headers(self) -> None:
        job_id = "draft_job_header_wait_cancel_test"
        request = DraftRequest(
            base_url="http://127.0.0.1:9999/v1",
            model="test-model",
            character_ids=["cast-a"],
            target_minutes=1,
            theme="ヘッダー待機中のキャンセルを確認するテストテーマです。",
        )
        started = threading.Event()
        released = threading.Event()

        class BlockingConnection:
            closed = False

            def request(self, *_args, **_kwargs) -> None:
                return None

            def getresponse(self):
                started.set()
                released.wait(2)
                if self.closed:
                    raise OSError("connection closed")
                raise AssertionError("header wait should have been cancelled")

            def close(self) -> None:
                self.closed = True
                released.set()

        connection = BlockingConnection()
        errors: list[Exception] = []
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {
                "id": job_id,
                "status": "generating",
                "cancelRequested": False,
                "appendedSceneIds": [],
                "chunks": [],
            }

        def request_headers() -> None:
            DRAFT_LLM_THREAD_CONTEXT.job_id = job_id
            try:
                openai_json_completion(
                    request,
                    system="system",
                    user={"test": True},
                    max_tokens=100,
                    should_cancel=lambda: bool(DRAFT_JOBS[job_id]["cancelRequested"]),
                )
            except Exception as error:
                errors.append(error)
            finally:
                DRAFT_LLM_THREAD_CONTEXT.job_id = None

        try:
            with patch("server.app.http.client.HTTPConnection", return_value=connection):
                worker = threading.Thread(target=request_headers)
                worker.start()
                self.assertTrue(started.wait(1))
                cancelled = cancel_draft_job(job_id)
                self.assertEqual(cancelled["status"], "cancelled")
                self.assertTrue(connection.closed)
                worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], GenerationCancelled)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

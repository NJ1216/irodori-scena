"""Ollama HTTP -> contract -> job -> atomic project save regression tests."""
from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException

import server.app  # noqa: F401
from server.registry import deps
from ollama_http_fixture import OllamaServer, dialogue, outline


class OllamaDraftPipelineTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        # Isolate filesystem settings and resource management, never completion or save.
        self.stack.enter_context(patch("server.modules.windows_external_memory._is_windows_local", return_value=False))
        self.stack.enter_context(patch("server.modules.llm_registry.resolve_llm_settings", return_value={"temperature": .8}))
        self.stack.enter_context(patch("server.modules.llm_registry_metadata.record_llm_usage"))
        self.stack.enter_context(patch("server.modules.workspace.record_draft_yield"))
        self.stack.enter_context(patch("server.modules.constants.LLM_DEBUG_ROOT", self.directory / "debug"))
        self.stack.enter_context(patch("server.modules.constants.LLM_DEBUG_ENABLED", True))
        previous = deps.ACTIVE_PROJECT_ROOT
        deps.activate_project_root(self.directory / "project", persist=False)
        self.addCleanup(lambda: deps.activate_project_root(previous, persist=False))
        self.characters = [{"id": "a", "name": "彩", "profileDetails": {},
                            "referenceAudioUrl": "", "referenceFile": "", "createdAt": 0}]
        project = deps.default_project()
        project["characters"] = self.characters
        deps.write_project(project)
        self.original = deps.read_project()
        self.job_id = "ollama-http-pipeline"
        self.addCleanup(lambda: deps.DRAFT_JOBS.pop(self.job_id, None))

    def run_job(self, server, *, settings=None):
        request = deps.DraftRequest(provider="ollama", base_url=server.base_url, model="fixture",
            character_ids=["a"], target_minutes=1, theme="配信を始めて近況を話し、自然に締める。演出は穏やかに。")
        deps.DRAFT_JOBS[self.job_id] = {"id": self.job_id, "status": "planning", "startedAt": 0,
            "cancelRequested": False, "chunks": [], "appendedLines": 0, "estimatedSeconds": 0,
            "benchmarkSeed": 42}
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value=settings or {"temperature": .8}), \
             patch("server.modules.draft_capability.local_memory_gib", return_value=None):
            deps.run_draft_job(self.job_id, request, self.characters)
        return deps.DRAFT_JOBS[self.job_id]

    def test_cold_and_loaded_keep_32k_seed_and_saved_lines(self):
        def respond(payload):
            return (outline() if "records" in payload["format"]["properties"] else dialogue(payload), "stop")
        for loaded in (False, True):
            with self.subTest(loaded=loaded), OllamaServer(respond, loaded=loaded) as server:
                job = self.run_job(server)
                self.assertEqual(job["status"], "completed", job.get("error"))
                self.assertEqual(job["completedDevelopments"], job["plannedDevelopments"])
                self.assertEqual(job["usedDialogueBatchSizes"], [1, 1, 1])
                sends = [(path, payload) for path, payload in server.requests if path != "/api/show"]
                self.assertEqual(any(path == "/api/generate" for path, _ in sends), not loaded)
                for path, payload in sends:
                    if path == "/api/generate":
                        self.assertNotIn("options", payload)
                        self.assertNotIn("prompt", payload)
                    else:
                        self.assertEqual(payload["options"]["num_ctx"], 32768)
                        self.assertEqual(payload["options"]["seed"], 42)
                        self.assertFalse(payload["think"])
                for item in job["dialogueBatchHistory"]:
                    self.assertLessEqual(item["inputTokenEstimate"] + item["outputTokenLimit"] + item["safetyMargin"],
                                         item["selectedContext"])
                saved = deps.read_project()
                self.assertEqual(sum(len(s["lines"]) for s in saved["scenes"][-1:]), job["appendedLines"])

    def test_partial_scene_continues_and_unstarted_sources_are_not_abandoned(self):
        calls = 0
        def respond(payload):
            nonlocal calls
            if "records" in payload["format"]["properties"]:
                return outline(3), "stop"
            calls += 1
            sources = json.loads(dialogue(payload, tag=str(calls)))
            for source, scene in sources.items():
                scene["lines"][0]["text"] = f"{source}の話を進めます。その{calls}。"
            content = json.dumps(sources, ensure_ascii=False)
            if calls == 2:
                sources = json.loads(content)
                first = next(iter(sources))
                line = sources[first]["lines"][0]
                line["text"] = "まだ話の途中です。"
                return '{' + json.dumps(first) + ':{"lines":[' + json.dumps(line, ensure_ascii=False)[:-1], "length"
            return content, "stop"
        with OllamaServer(respond) as server:
            job = self.run_job(server)
        self.assertEqual(job["status"], "completed", job.get("error"))
        self.assertEqual(job["completedDevelopments"], 3)
        self.assertTrue(job["partialContinuationUsed"])
        self.assertGreater(job["appendedLines"], 3)
        self.assertEqual(job["dialogueBatchHistory"][1]["pendingSources"], ["D1.2"])

    def test_four_k_fails_before_dialogue_and_keeps_project(self):
        with OllamaServer(lambda _payload: (outline(), "stop")) as server:
            job = self.run_job(server, settings={"contextLimit": 4096})
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["failureCode"], "draft_context_insufficient")
        self.assertEqual(deps.read_project(), self.original)
        self.assertTrue((self.directory / "debug" / self.job_id / "job-result.json").exists())

    def test_no_new_line_stops_and_partial_save_does_not_count_missing_scenes(self):
        calls = 0
        def respond(payload):
            nonlocal calls
            if "records" in payload["format"]["properties"]:
                return outline(), "stop"
            calls += 1
            return (dialogue(payload) if calls == 1 else '{"D1.2":{"lines":[]}}'), "stop"
        with OllamaServer(respond) as server:
            job = self.run_job(server)
        self.assertEqual(calls, 3)
        self.assertEqual(job["status"], "completed")
        self.assertIn("incomplete_developments", job["partialReason"])
        self.assertEqual(job["completedChapters"], 0)
        self.assertEqual(job["generatedSceneCount"], 1)

    def test_incomplete_scene_uses_finite_budget_and_keeps_all_new_lines(self):
        calls = 0
        def respond(payload):
            nonlocal calls
            if "records" in payload["format"]["properties"]:
                return outline(1), "stop"
            calls += 1
            return dialogue(payload, tag=str(calls), complete=False), "length"
        with OllamaServer(respond) as server:
            job = self.run_job(server)
        self.assertEqual(calls, 3)
        self.assertEqual(job["plannedDialogueCalls"], 5)
        self.assertEqual(job["completedDevelopments"], 0)
        self.assertEqual(job["appendedLines"], calls)
        self.assertIn("incomplete_developments", job["partialReason"])

    def test_cancel_leaves_original_project_and_raw_diagnostics(self):
        def respond(payload):
            if "records" in payload["format"]["properties"]:
                return outline(), "stop"
            deps.DRAFT_JOBS[self.job_id]["cancelRequested"] = True
            return dialogue(payload), "stop"
        with OllamaServer(respond) as server:
            job = self.run_job(server)
        self.assertEqual(job["status"], "cancelled")
        self.assertEqual(deps.read_project(), self.original)
        self.assertTrue((self.directory / "debug" / self.job_id / "dialogue-01.transport.json").exists())

    def test_save_failure_is_distinct_and_keeps_accepted_diagnostics(self):
        def respond(payload):
            return (outline(1) if "records" in payload["format"]["properties"] else dialogue(payload), "stop")
        with OllamaServer(respond) as server, patch("server.modules.project_repository.write_project",
                                                  side_effect=OSError("disk full")):
            job = self.run_job(server)
        self.assertEqual(job["failureCode"], "draft_save_failed")
        self.assertEqual(deps.read_project(), self.original)
        self.assertGreater(job["actualCharacters"], 0)

    def test_project_switch_never_receives_old_draft(self):
        other_root = self.directory / "other"
        original_root = deps.ACTIVE_PROJECT_ROOT
        deps.activate_project_root(other_root, persist=False)
        deps.write_project(deps.default_project())
        other = deps.read_project()
        deps.activate_project_root(original_root, persist=False)
        def respond(payload):
            if "records" in payload["format"]["properties"]:
                return outline(1), "stop"
            deps.activate_project_root(other_root, persist=False)
            return dialogue(payload), "stop"
        with OllamaServer(respond) as server:
            job = self.run_job(server)
        self.assertEqual(job["failureCode"], "draft_project_changed")
        self.assertEqual(deps.read_project(), other)
        deps.activate_project_root(original_root, persist=False)
        self.assertEqual(deps.read_project(), self.original)

    def test_cancel_after_atomic_commit_cannot_undo_save_before_final_publication(self):
        self.job_id = "ai_job_commit_boundary"
        deps.DRAFT_JOBS[self.job_id] = {"id": self.job_id, "status": "generating", "cancelRequested": False}
        line = {"id": "saved-line", "characterId": "a", "text": "保存した本文。", "takes": [],
                "selectedTakeId": None, "speechRate": 1, "gapSeconds": .7}
        deps.append_directed_draft(self.job_id, title="保存済み",
            chunks=[{"scenes": [{"id": "saved-scene", "title": "完了", "lines": [line]}],
                     "spoken": 7, "discarded_duplicates": 0}], script_cast_contexts={})
        saved = deps.read_project()
        for cancel in (deps.cancel_draft_job, deps.cancel_ai_job):
            with self.assertRaises(HTTPException) as error:
                cancel(self.job_id)
            self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(deps.read_project(), saved)
        self.assertNotIn("_saveCommitted", deps.public_draft_job(deps.DRAFT_JOBS[self.job_id]))

    def append_fixture_draft(self):
        line = {"id": "generated-line", "characterId": "a", "text": "生成本文。", "takes": []}
        deps.DRAFT_JOBS[self.job_id] = {
            "id": self.job_id, "status": "generating", "cancelRequested": False,
        }
        deps.append_directed_draft(
            self.job_id, title="生成済み",
            chunks=[{"scenes": [{"id": "generated-scene", "title": "生成", "lines": [line]}],
                     "spoken": 5, "discarded_duplicates": 0}],
            script_cast_contexts={},
        )

    def test_generated_draft_replaces_scenes_when_existing_script_has_no_lines(self):
        self.append_fixture_draft()
        saved = deps.read_project()
        self.assertEqual([scene["id"] for scene in saved["scenes"]], ["generated-scene"])

    def test_generated_draft_replaces_all_blank_lines_and_removes_their_takes(self):
        project = deps.read_project()
        project["scenes"] = [
            {"id": "blank-a", "title": "空1", "lines": []},
            {"id": "blank-b", "title": "空2", "lines": [{
                "id": "blank-line", "characterId": "a", "text": " \n\t", "stageDirection": "演技指示",
                "speechRate": 1.2, "takes": [{
                    "id": "old-take", "audioUrl": "/media/takes/blank-line/old-take.wav",
                    "seed": 1, "quality": "fast", "createdAt": 0,
                }],
            }]},
        ]
        deps.write_project(project)
        take_dir = deps.MEDIA_ROOT / "takes" / "blank-line"
        take_dir.mkdir(parents=True)
        (take_dir / "old-take.wav").write_bytes(b"wav")

        self.append_fixture_draft()

        saved = deps.read_project()
        self.assertEqual([scene["id"] for scene in saved["scenes"]], ["generated-scene"])
        self.assertFalse(take_dir.exists())

    def test_generated_draft_preserves_all_existing_scenes_when_any_body_has_text(self):
        project = deps.read_project()
        project["scenes"] = [
            {"id": "blank", "title": "空", "lines": [
                {"id": "blank-line", "characterId": "a", "text": ""},
            ]},
            {"id": "written", "title": "本文", "lines": [
                {"id": "written-line", "characterId": "a", "text": "既存本文"},
            ]},
        ]
        deps.write_project(project)

        self.append_fixture_draft()

        self.assertEqual(
            [scene["id"] for scene in deps.read_project()["scenes"]],
            ["blank", "written", "generated-scene"],
        )

    def test_failed_empty_script_replacement_restores_project_and_takes(self):
        project = deps.read_project()
        project["scenes"] = [{"id": "blank", "title": "空", "lines": [
            {"id": "blank-line", "characterId": "a", "text": ""},
        ]}]
        deps.write_project(project)
        original = deps.read_project()
        take_dir = deps.MEDIA_ROOT / "takes" / "blank-line"
        take_dir.mkdir(parents=True)
        (take_dir / "old-take.wav").write_bytes(b"wav")

        with patch("server.modules.project_repository.write_project", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.append_fixture_draft()

        self.assertEqual(deps.read_project(), original)
        self.assertTrue((take_dir / "old-take.wav").exists())

    def test_project_identity_is_captured_before_worker_start(self):
        def respond(payload):
            return (outline(1) if "records" in payload["format"]["properties"] else dialogue(payload), "stop")
        original_root = deps.ACTIVE_PROJECT_ROOT
        with OllamaServer(respond) as server:
            request = deps.DraftRequest(provider="ollama", base_url=server.base_url, model="fixture",
                character_ids=["a"], target_minutes=1, theme="開始後にプロジェクトを切り替える検証。")
            for unified in (False, True):
                with self.subTest(unified=unified):
                    deps.activate_project_root(original_root, persist=False)
                    with patch("server.modules.job_routes.threading.Thread.start"):
                        initial = (deps.start_ai_job(deps.AiJobRequest(mode="draft", **request.model_dump()))
                                   if unified else deps.start_draft_job(request))
                    self.job_id = initial["id"]
                    self.addCleanup(lambda job_id=self.job_id: deps.DRAFT_JOBS.pop(job_id, None))
                    deps.activate_project_root(self.directory / "switched-before-worker", persist=False)
                    other = deps.default_project()
                    other["characters"] = self.characters
                    deps.write_project(other)
                    other = deps.read_project()
                    deps.run_draft_job(self.job_id, request, self.characters)
                    job = deps.DRAFT_JOBS[self.job_id]
                    self.assertEqual(job["failureCode"], "draft_project_changed")
                    self.assertEqual(deps.read_project(), other)
                    self.assertNotIn("_projectId", initial)

    def test_removing_repeated_last_line_does_not_reopen_completed_scene(self):
        calls, first_line = 0, None
        def respond(payload):
            nonlocal calls, first_line
            if "records" in payload["format"]["properties"]:
                return outline(2), "stop"
            calls += 1
            value = json.loads(dialogue(payload))
            scene = next(iter(value.values()))
            if first_line is None:
                first_line = scene["lines"][0]
            else:
                scene["lines"].append(first_line)
            return json.dumps(value, ensure_ascii=False), "stop"
        with OllamaServer(respond) as server:
            job = self.run_job(server)
        self.assertEqual(calls, 2)
        self.assertEqual(job["completedDevelopments"], 2)
        self.assertEqual(job["appendedLines"], 2)
        self.assertIn("repetition", job["dialogueBatchHistory"][-1]["shrinkReasons"])

    def test_ending_received_before_pending_scene_stops_further_generation(self):
        calls = 0
        def respond(payload):
            nonlocal calls
            if "records" in payload["format"]["properties"]:
                return outline(3), "stop"
            calls += 1
            value = json.loads(dialogue(payload))
            if calls == 2:
                value["D1.2"]["complete"] = False
            return json.dumps(value, ensure_ascii=False), "stop"
        with OllamaServer(respond) as server:
            job = self.run_job(server)
        self.assertEqual(calls, 3)
        self.assertEqual(job["completedDevelopments"], 2)
        self.assertEqual(job["appendedLines"], 3)
        self.assertEqual(job["completedChapters"], 0)
        self.assertIn("incomplete_developments", job["partialReason"])


if __name__ == "__main__":
    unittest.main()

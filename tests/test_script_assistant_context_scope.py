import scena_test_isolation  # noqa: F401
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from server.app import app as _app  # noqa: F401
from server.modules.runtime_state import SCRIPT_ASSISTANT_JOBS, SCRIPT_ASSISTANT_PROPOSALS
from server.modules.script_assistant_fitting import context_limit
from server.modules.script_assistant_jobs import run_script_assistant_job
from server.modules.script_assistant_models import ScriptAssistantRequest
from server.registry import deps


class ScriptAssistantContextScopeTests(TestCase):
    def setUp(self) -> None:
        SCRIPT_ASSISTANT_JOBS.clear()
        SCRIPT_ASSISTANT_PROPOSALS.clear()

    def test_job_uses_selected_model_context_profile_and_clears_it(self) -> None:
        project = {
            "title": "test", "characters": [{"id": "a", "name": "彩", "profile": "落ち着いている"}],
            "settings": {"speechRate": 1.2, "lineGap": 0.7},
            "scenes": [{"id": "scene-1", "title": "一", "lines": [
                {"id": "target", "characterId": "a", "text": "始めよう", "stageDirection": ""},
            ]}],
        }
        request = ScriptAssistantRequest(
            operation="rewrite", line_ids=["target"], character_ids=["a"],
            base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        job_id = "script_assistant_job_context_profile"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        observed_limits: list[int] = []

        def generate(*_args, **_kwargs):
            observed_limits.append(context_limit())
            return {"id": "group", "warnings": []}

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.draft_capability.build_direction_capability_profile", return_value={
                "provider": "openai", "contextCeiling": 16384, "effectiveContext": 16384,
            }) as capability,
            patch("server.modules.script_assistant_jobs._generate_group", side_effect=generate),
        ):
            run_script_assistant_job(job_id, request, project)

        capability.assert_called_once_with(request)
        self.assertEqual(observed_limits, [16384])
        self.assertIsNone(getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "capability_profile", None))

    def test_complete_rewrite_sends_every_selected_generation_candidate(self) -> None:
        characters = [
            {"id": "a", "name": "彩", "profile": "落ち着いている"},
            {"id": "b", "name": "蓮", "profile": "快活"},
            *[
                {"id": f"cast-{index}", "name": f"候補{index}", "profile": f"秘密の詳細{index}"}
                for index in range(2, 10)
            ],
        ]
        project = {
            "title": "test", "characters": characters,
            "settings": {"speechRate": 1.2, "lineGap": 0.7},
            "scenes": [{"id": "scene-1", "title": "一", "lines": [
                {"id": "one", "characterId": "a", "text": "始めよう", "stageDirection": ""},
                {"id": "two", "characterId": "b", "text": "うん", "stageDirection": ""},
            ]}],
        }
        request = ScriptAssistantRequest(
            operation="rewrite", line_ids=["one", "two"],
            character_ids=[item["id"] for item in characters], target_line_count=2,
            base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        job_id = "script_assistant_cast_scope"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_fitting.context_limit", return_value=32768),
            patch("server.modules.script_assistant_jobs._call", side_effect=[
                "二人の応答で到達点へ進む。", "A|別の始まり||cue=NONE\nB|応じる||cue=NONE",
            ]) as call,
        ):
            run_script_assistant_job(job_id, request, project)
        plan_user = call.call_args_list[0].kwargs["user"]
        generation_user = call.call_args_list[1].kwargs["user"]
        self.assertEqual(len(plan_user["selected_cast_index"]), 10)
        self.assertNotIn("profile", plan_user["selected_cast_index"][0])
        self.assertEqual(
            {item["name"] for item in generation_user["selected_casts"]},
            {item["name"] for item in characters},
        )
        self.assertTrue(all(item["generation_candidate"] for item in generation_user["selected_casts"]))
        self.assertNotIn("original_target_rows", generation_user)
        self.assertNotIn("始めよう", str(generation_user))

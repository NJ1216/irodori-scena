from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import app as _app  # noqa: F401
from server.modules.runtime_state import SCRIPT_ASSISTANT_JOBS, SCRIPT_ASSISTANT_PROPOSALS
from server.modules.script_assistant_jobs import run_script_assistant_job
from server.modules.script_assistant_models import ScriptAssistantRequest


def _line(line_id: str, cast: str, text: str) -> dict:
    return {"id": line_id, "characterId": cast, "text": text, "stageDirection": "", "takes": []}


class LlmContextCompilerIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        SCRIPT_ASSISTANT_JOBS.clear()
        SCRIPT_ASSISTANT_PROPOSALS.clear()

    def test_complete_rewrite_keeps_all_candidates_and_context_casts(self) -> None:
        value = {
            "title": "test",
            "characters": [
                {"id": "a", "name": "彩", "profile": "落ち着いている"},
                {"id": "b", "name": "蓮", "profile": "快活"},
                {"id": "c", "name": "文脈役", "profile": "文脈だけの人物"},
                {"id": "d", "name": "追加役", "profile": "新しく発話する候補"},
            ],
            "settings": {"speechRate": 1.2, "lineGap": 0.7},
            "scenes": [{"id": "scene", "title": "一", "lines": [
                _line("before", "a", "先に待っている。"), _line("target", "b", "元の台詞"),
                _line("after", "c", "続きを促す。"),
            ]}],
        }
        request = ScriptAssistantRequest(
            operation="rewrite", line_ids=["target"], character_ids=["a", "b", "d"],
            base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        job_id = "script_assistant_job_context_casts"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        with (
            patch("server.modules.script_assistant_fitting.context_limit", return_value=32768),
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", side_effect=[
                "別経路で合流する。", "NORMAL|D|新しい台詞。||direction=静かに",
            ]) as call,
        ):
            run_script_assistant_job(job_id, request, value)
        cast = call.call_args_list[1].kwargs["user"]["selected_casts"]
        by_name = {item["name"]: item for item in cast}
        self.assertEqual(set(by_name), {"彩", "蓮", "追加役", "文脈役"})
        self.assertTrue(by_name["追加役"]["generation_candidate"])
        self.assertFalse(by_name["文脈役"]["generation_candidate"])
        self.assertEqual(SCRIPT_ASSISTANT_JOBS[job_id]["groups"][0]["rows"][0]["characterId"], "d")

    def test_eight_cast_rewrite_keeps_two_speakers_and_explicit_references_only(self) -> None:
        characters = [
            {"id": chr(97 + index), "name": f"人物{index + 1}", "profile": f"固有設定{index + 1}"}
            for index in range(8)
        ]
        value = {
            "title": "eight", "characters": characters,
            "settings": {"speechRate": 1.2, "lineGap": 0.7},
            "scenes": [{"id": "scene", "title": "後半", "lines": [
                _line("before", "a", "直前の発話"), _line("target", "b", "書き直す発話"),
                _line("after", "a", "直後の発話"),
            ]}],
        }
        request = ScriptAssistantRequest(
            operation="rewrite", line_ids=["target"], character_ids=["a", "b"],
            instruction="人物3と人物4が不在の理由に触れる", target_line_count=2,
            base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        job_id = "script_assistant_job_eight_cast_scope"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        with (
            patch("server.modules.script_assistant_fitting.context_limit", return_value=32768),
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", side_effect=[
                "不在の二人について確認する。", "NORMAL|A|二人は別室にいる。||direction=説明して",
            ]) as call,
        ):
            run_script_assistant_job(job_id, request, value)
        cast = call.call_args_list[1].kwargs["user"]["selected_casts"]
        self.assertEqual({item["name"] for item in cast}, {"人物1", "人物2", "人物3", "人物4"})
        self.assertEqual(
            {item["name"] for item in cast if item["generation_candidate"]},
            {"人物1", "人物2"},
        )

    def test_ambiguous_same_name_is_not_inferred_as_a_reference(self) -> None:
        from server.modules.script_assistant_context_packing import explicit_reference_ids

        project = {"characters": [
            {"id": "a", "name": "同名"}, {"id": "b", "name": "同名"}, {"id": "c", "name": "一意"},
        ]}
        self.assertEqual(explicit_reference_ids(project, "同名と一意について話す"), {"c"})


if __name__ == "__main__":
    unittest.main()

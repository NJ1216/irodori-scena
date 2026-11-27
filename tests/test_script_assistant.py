from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest


from server.app import app as _app  # noqa: F401
from server.modules.script_assistant_context import (
    prepare_script_assistant_groups,
    script_assistant_context,
)
from server.modules.script_assistant_jobs import (
    _direct_rows,
    _system_prompt,
)
from server.modules.script_assistant_models import ScriptAssistantApplyRequest, ScriptAssistantRequest


def line(line_id: str, cast: str, text: str | None = None, **extra):
    return {"id": line_id, "characterId": cast, "text": text or line_id, "stageDirection": "",
            "takes": [], "selectedTakeId": None, **extra}


def project(*scenes):
    return {
        "title": "test", "characters": [
            {"id": "a", "name": "彩", "profile": "落ち着いている"},
            {"id": "b", "name": "蓮", "profile": "快活"},
        ],
        "settings": {"speechRate": 1.2, "lineGap": 0.7}, "scenes": list(scenes),
    }


def request(operation="rewrite", line_ids=None, **extra):
    character_ids = extra.pop("character_ids", ["a", "b"])
    scene_id = extra.pop("scene_id", "scene-1" if operation == "insert" else "")
    return ScriptAssistantRequest(
        operation=operation, line_ids=["target"] if line_ids is None else line_ids, character_ids=character_ids,
        scene_id=scene_id,
        base_url="http://127.0.0.1:9999/v1", model="test-model", **extra,
    )


class ScriptAssistantContextTests(unittest.TestCase):
    def test_overlap_setting_is_independent_from_simultaneous_cues(self) -> None:
        overlap = request(operation="insert", line_ids=[], simultaneous_cues=False, overlapping_speech=True, performance_gap_min=-2)
        cues = request(operation="insert", line_ids=[], simultaneous_cues=True, overlapping_speech=False, performance_gap_min=-2)
        self.assertEqual(overlap.performance_gap_min, -2)
        self.assertEqual(cues.performance_gap_min, 0)

    def test_cast_settings_control_emoji_and_dialogue_guidance(self) -> None:
        assistant_request = request(operation="insert", line_ids=[], cast_settings={
            "a": {"emoji_expressions": True, "filler_richness": True, "appearance_priority": "main"},
            "b": {"emoji_expressions": False, "filler_richness": False, "appearance_priority": "supporting"},
        })
        prompt = _system_prompt(assistant_request, {"fixed": False})
        self.assertIn("fillers", prompt)
        self.assertIn("priority main", prompt)
        rows = _direct_rows(assistant_request, [
            {"character_id": "a", "text": "おはよう", "integrated_direction": {"emoji": "😊@おはよう"}},
            {"character_id": "b", "text": "待って", "integrated_direction": {"emoji": "😊@待って"}},
        ], [])
        self.assertIn("😊", rows[0]["text"])
        self.assertEqual(rows[1]["text"], "待って")

    def test_context_excludes_disabled_rows_and_reads_three_rows_across_scenes(self) -> None:
        value = project(
            {"id": "scene-1", "title": "一", "lines": [line("before", "a"), line("disabled", "b", enabled=False), line("target", "a")]},
            {"id": "scene-2", "title": "二", "lines": [line("off", "a", enabled=False), line("after-1", "b"), line("after-2", "a"), line("after-3", "b")]},
        )
        group = prepare_script_assistant_groups(value, request())[0]
        context = script_assistant_context(value, group)
        self.assertEqual([row["line"]["id"] for row in context["recentRows"]], ["before"])
        self.assertEqual([row["line"]["id"] for row in context["selectedRows"]], ["target"])
        self.assertEqual([row["line"]["id"] for row in context["followingRows"]], ["after-1", "after-2", "after-3"])

    def test_disabled_selected_row_remains_an_explicit_target(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("before", "a"), line("target", "b", enabled=False)]})
        context = script_assistant_context(value, prepare_script_assistant_groups(value, request())[0])
        self.assertEqual(context["selectedRows"][0]["line"]["id"], "target")
        self.assertEqual(context["recentRows"][0]["line"]["id"], "before")

    def test_long_old_context_is_separated_for_summarization(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [
            line(f"old-{index}", "a", "長" * 1000) for index in range(15)
        ] + [line("target", "b")]})
        context = script_assistant_context(value, prepare_script_assistant_groups(value, request())[0])
        self.assertGreater(len(context["middleRows"]), 0)
        self.assertGreater(len(context["recentRows"]), 0)

    def test_cross_scene_line_target_is_allocated_by_selected_count(self) -> None:
        value = project(
            {"id": "scene-1", "title": "一", "lines": [line("a1", "a")]},
            {"id": "scene-2", "title": "二", "lines": [line("b1", "a"), line("b2", "b")]},
        )
        groups = prepare_script_assistant_groups(value, request(line_ids=["a1", "b1", "b2"], target_line_count=6))
        self.assertEqual([group["targetLineCount"] for group in groups], [2, 4])

    def test_sparse_rewrite_is_fixed_to_selected_rows(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("a1", "a"), line("anchor", "b"), line("a2", "a")]})
        groups = prepare_script_assistant_groups(value, request(line_ids=["a1", "a2"], target_line_count=9))
        self.assertTrue(groups[0]["fixed"])
        self.assertEqual(groups[0]["targetLineCount"], 2)

    def test_integrated_assistant_has_no_eight_cast_limit(self) -> None:
        cast_ids = [f"cast-{index}" for index in range(20)]
        value = ScriptAssistantRequest(operation="insert", scene_id="scene", character_ids=cast_ids)
        self.assertEqual(len(value.character_ids), 20)

    def test_cast_composition_accepts_one_thousand_fixed_lines(self) -> None:
        line_ids = [f"line-{index}" for index in range(1000)]
        value = ScriptAssistantRequest(
            operation="cast-compose",
            line_ids=line_ids,
            character_ids=["a"],
            target_line_count=len(line_ids),
        )
        self.assertEqual(value.target_line_count, 1000)
        with self.assertRaises(ValueError):
            ScriptAssistantRequest(
                operation="cast-compose", line_ids=[*line_ids, "line-1000"],
                character_ids=["a"], target_line_count=1001,
            )
        apply_request = ScriptAssistantApplyRequest(
            proposal_id="proposal", source_signature="0" * 64,
            accepted_group_ids=[f"group-{index}" for index in range(1000)],
        )
        self.assertEqual(len(apply_request.accepted_group_ids), 1000)

    def test_cast_composition_allows_selected_casts_without_target_rows(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("target", "a")]})
        groups = prepare_script_assistant_groups(
            value,
            request(operation="cast-compose", character_ids=["a", "b"]),
        )
        self.assertEqual(groups[0]["targetLineIds"], ["target"])



if __name__ == "__main__":
    unittest.main()

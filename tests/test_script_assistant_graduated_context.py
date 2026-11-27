import scena_test_isolation  # noqa: F401
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from server.app import app as _app  # noqa: F401
from server.modules.script_assistant_context import prepare_script_assistant_groups, script_assistant_context
from server.modules.script_assistant_context_packing import pack_script_assistant_context
from server.modules.script_assistant_models import ScriptAssistantRequest
from server.modules.script_assistant_jobs import run_script_assistant_job
from server.modules.script_assistant_summary import clear_script_assistant_summary_cache
from server.modules.runtime_state import SCRIPT_ASSISTANT_JOBS, SCRIPT_ASSISTANT_PROPOSALS


def _line(line_id: str, cast: str, text: str, **extra):
    return {"id": line_id, "characterId": cast, "text": text, "stageDirection": "", **extra}


def _project(*scenes):
    return {
        "id": "project", "title": "test",
        "characters": [{"id": "a", "name": "彩"}, {"id": "b", "name": "蓮"}],
        "settings": {"speechRate": 1.2, "lineGap": 0.7}, "scenes": list(scenes),
    }


def _insert(scene_id: str, before_line_id: str) -> ScriptAssistantRequest:
    return ScriptAssistantRequest(
        operation="insert", scene_id=scene_id, before_line_id=before_line_id,
        line_ids=[], character_ids=["a", "b"], target_line_count=2,
        base_url="http://127.0.0.1:9999/v1", model="test-model",
    )


class ScriptAssistantGraduatedContextTests(TestCase):
    def setUp(self) -> None:
        clear_script_assistant_summary_cache()
        SCRIPT_ASSISTANT_JOBS.clear()
        SCRIPT_ASSISTANT_PROPOSALS.clear()

    def test_six_chapter_insert_has_distant_middle_and_metadata_free_near_rows(self) -> None:
        scenes = []
        for chapter in "ABCDEF":
            count = 300 if chapter == "F" else 10
            scenes.append({
                "id": f"scene-{chapter}", "title": chapter,
                "lines": [
                    _line(
                        f"{chapter}-{index}", "a" if index % 2 == 0 else "b", f"{chapter}台詞{index}",
                        stageDirection="秘密のト書き", speechRate=1.7, gapSeconds=2.5,
                        cueId="秘密のcue", startOffsetSeconds=3.0,
                    )
                    for index in range(count)
                ],
            })
        value = _project(*scenes)
        request = _insert("scene-F", "F-250")
        context = script_assistant_context(value, prepare_script_assistant_groups(value, request)[0])
        calls = []

        def summarize(*_args, **kwargs):
            calls.append(kwargs["user"])
            return f"要約{len(calls)}"

        packed = pack_script_assistant_context(
            request, "job", context, Path("/tmp/script-assistant-test"), call=summarize,
        )
        self.assertEqual([item["chapter"] for item in packed["distant_context"]], list("ABCDE"))
        self.assertTrue(packed["middle_context"])
        self.assertEqual([row["text"] for row in packed["recent"]], ["F台詞247", "F台詞248", "F台詞249"])
        self.assertEqual([row["text"] for row in packed["following"]], ["F台詞250", "F台詞251", "F台詞252"])
        self.assertEqual(set(packed["recent"][0]), {"speaker", "text"})
        serialized = str([packed["recent"], packed["following"]])
        for prohibited in ("秘密のト書き", "speechRate", "gapSeconds", "秘密のcue", "startOffsetSeconds"):
            self.assertNotIn(prohibited, serialized)

    def test_single_long_scene_uses_fifty_line_virtual_chapters(self) -> None:
        value = _project({
            "id": "scene-1", "title": "章分けなし",
            "lines": [_line(f"row-{index}", "a", f"台詞{index}") for index in range(300)],
        })
        request = _insert("scene-1", "row-250")
        context = script_assistant_context(value, prepare_script_assistant_groups(value, request)[0])
        self.assertEqual([unit["id"] for unit in context["distantUnits"]], [
            "scene-1:0", "scene-1:1", "scene-1:2", "scene-1:3", "scene-1:4",
        ])
        self.assertEqual(context["middleRows"], [])

    def test_cache_reuses_unchanged_blocks_and_invalidates_only_changed_block(self) -> None:
        value = _project({
            "id": "scene-1", "title": "長編",
            "lines": [_line(f"row-{index}", "a", f"台詞{index}") for index in range(300)],
        })
        request = _insert("scene-1", "row-260")
        calls = []

        def summarize(*_args, **kwargs):
            calls.append(kwargs["user"])
            return "利用可能な要約"

        def pack() -> None:
            context = script_assistant_context(value, prepare_script_assistant_groups(value, request)[0])
            pack_script_assistant_context(
                request, "job", context, Path("/tmp/script-assistant-test"), call=summarize,
            )

        pack()
        initial = len(calls)
        pack()
        self.assertEqual(len(calls), initial)
        value["scenes"][0]["lines"][10]["text"] = "変更した台詞"
        pack()
        self.assertEqual(len(calls), initial + 1)

    def test_beginning_end_and_fifty_line_boundary_keep_exact_near_rows(self) -> None:
        value = _project({
            "id": "scene-1", "title": "長編",
            "lines": [_line(f"row-{index}", "a", f"台詞{index}") for index in range(100)],
        })
        beginning = script_assistant_context(value, prepare_script_assistant_groups(value, _insert("scene-1", "row-0"))[0])
        self.assertEqual(beginning["recentRows"], [])
        self.assertEqual([row["line"]["id"] for row in beginning["followingRows"]], ["row-0", "row-1", "row-2"])

        end_request = ScriptAssistantRequest(
            operation="insert", scene_id="scene-1", line_ids=[], character_ids=["a"], target_line_count=1,
            base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        ending = script_assistant_context(value, prepare_script_assistant_groups(value, end_request)[0])
        self.assertEqual([row["line"]["id"] for row in ending["recentRows"]], ["row-97", "row-98", "row-99"])
        self.assertEqual(ending["followingRows"], [])

        rewrite = ScriptAssistantRequest(
            operation="rewrite", line_ids=["row-49", "row-50", "row-51"], character_ids=["a"],
            target_line_count=3, base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        crossing = script_assistant_context(value, prepare_script_assistant_groups(value, rewrite)[0])
        self.assertEqual([row["line"]["id"] for row in crossing["recentRows"]], ["row-46", "row-47", "row-48"])
        self.assertEqual([row["line"]["id"] for row in crossing["followingRows"]], ["row-52", "row-53", "row-54"])

    def test_long_rewrite_summarizes_target_and_never_sends_target_text_to_generation(self) -> None:
        rows = [_line(f"row-{index}", "a", f"原文固有{index}") for index in range(100)]
        value = _project({"id": "scene-1", "title": "長編", "lines": rows})
        request = ScriptAssistantRequest(
            operation="rewrite", line_ids=[row["id"] for row in rows], character_ids=["a"],
            target_line_count=1, base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        job_id = "long-rewrite"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        calls = []

        def complete(*_args, **kwargs):
            calls.append(kwargs)
            if kwargs["feature"] == "script-assistant-summary":
                return "維持事実と到達点"
            if kwargs["feature"] == "script-assistant-rewrite-plan":
                return "別の会話経路で到達する"
            return "A|新しい一行||cue=NONE"

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", side_effect=complete),
        ):
            run_script_assistant_job(job_id, request, value)
        self.assertEqual(SCRIPT_ASSISTANT_JOBS[job_id]["status"], "completed")
        plan = next(item["user"] for item in calls if item["feature"] == "script-assistant-rewrite-plan")
        generation = next(item["user"] for item in calls if item["feature"] == "script-assistant-dialogue")
        self.assertEqual(plan["original_target_rows"], [])
        self.assertIn("維持事実", plan["target_segment_summaries"])
        self.assertNotIn("original_target_rows", generation)
        self.assertNotIn("原文固有", str(generation))

    def test_lines_189_to_194_rewrite_reaches_generation_with_32k_context(self) -> None:
        rows = [_line(f"row-{index}", "a" if index % 2 == 0 else "b", f"台詞{index}") for index in range(250)]
        value = _project({"id": "scene-1", "title": "長編", "lines": rows})
        selected = [f"row-{index}" for index in range(189, 195)]
        request = ScriptAssistantRequest(
            operation="rewrite", line_ids=selected, character_ids=["a", "b"], target_line_count=6,
            base_url="http://127.0.0.1:9999/v1", model="32k-model",
        )
        job_id = "rewrite-189-194"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        generated = "\n".join(f"{'A' if index % 2 == 0 else 'B'}|新台詞{index}||cue=NONE" for index in range(6))
        calls = []

        def complete(*_args, **kwargs):
            calls.append(kwargs)
            return {
                "script-assistant-summary": "継続要約",
                "script-assistant-rewrite-plan": "別経路の方針",
                "script-assistant-dialogue": generated,
            }[kwargs["feature"]]

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.draft_capability.build_direction_capability_profile", return_value={
                "provider": "openai", "contextCeiling": 32768, "effectiveContext": 32768,
            }),
            patch("server.modules.script_assistant_jobs._call", side_effect=complete),
        ):
            run_script_assistant_job(job_id, request, value)
        self.assertEqual(SCRIPT_ASSISTANT_JOBS[job_id]["status"], "completed")
        generation = next(item["user"] for item in calls if item["feature"] == "script-assistant-dialogue")
        self.assertNotIn("台詞189", str(generation))

    def test_context_only_cast_has_name_and_role_without_full_profile(self) -> None:
        value = _project({
            "id": "scene-1", "title": "一",
            "lines": [_line("before", "b", "蓮の発話"), _line("target", "a", "彩の発話")],
        })
        value["characters"][1].update({"profile": "送信してはいけない全文", "profileDetails": {"secret": "値"}})
        value["scriptCastContexts"] = {"b": "彩の友人"}
        request = ScriptAssistantRequest(
            operation="insert", scene_id="scene-1", before_line_id="target", line_ids=[], character_ids=["a"],
            target_line_count=1, base_url="http://127.0.0.1:9999/v1", model="test-model",
        )
        job_id = "reference-cast"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", return_value="A|追加台詞||cue=NONE") as call,
        ):
            run_script_assistant_job(job_id, request, value)
        cast = call.call_args.kwargs["user"]["selected_casts"]
        reference = next(item for item in cast if item["name"] == "蓮")
        self.assertEqual(reference["script_context"], "彩の友人")
        self.assertNotIn("profile", reference)
        self.assertNotIn("profile_details", reference)

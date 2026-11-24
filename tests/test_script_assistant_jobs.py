from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app as _app  # noqa: F401
from server.modules import constants
from server.modules.script_assistant_context import (
    script_assistant_signature,
)
from server.modules.script_assistant_cast_composition import restore_cast_composition_emojis
from server.modules.script_assistant_jobs import (
    _author_instruction,
    _system_prompt,
    apply_script_assistant_proposal,
    run_script_assistant_job,
)
from server.modules.script_assistant_intent import (
    _explicitly_requests_simultaneous,
    _minimum_simultaneous_lines,
)
from server.modules.script_assistant_models import ScriptAssistantApplyRequest, ScriptAssistantRequest
from server.modules.runtime_state import SCRIPT_ASSISTANT_JOBS, SCRIPT_ASSISTANT_PROPOSALS


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


class ScriptAssistantJobTests(unittest.TestCase):
    def setUp(self) -> None:
        SCRIPT_ASSISTANT_JOBS.clear()
        SCRIPT_ASSISTANT_PROPOSALS.clear()

    def test_paraphrase_aims_for_similar_length_without_exact_character_count(self) -> None:
        prompt = _system_prompt(request(operation="paraphrase"), {"fixed": True})
        self.assertIn("元行と同程度の長さ", prompt)
        self.assertIn("文字数の完全一致は要求しない", prompt)
        self.assertIn("行の追加・削除は禁止", prompt)
        self.assertIn("語彙、構文、情報の焦点、台詞のリズムのうち複数", prompt)
        self.assertIn("語尾だけを変えた提案は禁止", prompt)

    def test_blank_paraphrase_instruction_requires_more_than_an_ending_change(self) -> None:
        instruction = _author_instruction(request(operation="paraphrase"))
        self.assertIn("語彙・文構造・台詞のリズムを変え", instruction)
        self.assertIn("語尾だけの変更ではない", instruction)
        authored = request(operation="paraphrase", instruction="もっと素朴に")
        self.assertEqual(_author_instruction(authored), "もっと素朴に")

    def test_explicit_simultaneous_request_uses_the_parser_supported_cue_format(self) -> None:
        assistant_request = request(
            operation="rewrite", instruction="片方の掛け声で、動時発話の挨拶から始まる感じで。",
            simultaneous_cues=True,
        )
        prompt = _system_prompt(assistant_request, {"fixed": False}, "同時発話を必須にする。")
        self.assertTrue(_explicitly_requests_simultaneous(assistant_request))
        self.assertEqual(_minimum_simultaneous_lines(assistant_request), 3)
        self.assertIn("A|本文||emoji=NONE", prompt)
        self.assertIn("cue=SIM:S1", prompt)
        self.assertNotIn("SIM:S1|A", prompt)
        self.assertIn("通常発話だけで済ませてはならない", prompt)

    def test_explicit_simultaneous_rewrite_creates_and_applies_a_cue(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("target", "a")]})
        assistant_request = request(
            operation="rewrite", instruction="片方の掛け声で、動時発話の挨拶から始まる感じで。",
            simultaneous_cues=True, target_line_count=1,
        )
        job_id = "script_assistant_job_required_cue"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        generated = "\n".join([
            "A|せーの！||rate=1.0|gap=0.2|direction=元気に|cue=NONE",
            "A|おはよう！||rate=1.0|gap=0.7|direction=明るく|cue=SIM:S1",
            "B|おはようございます！||rate=1.0|gap=0.7|direction=明るく|cue=SIM:S1",
        ])
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", side_effect=["掛け声の後に二人が同時に挨拶する。", generated]) as call,
        ):
            run_script_assistant_job(job_id, assistant_request, value)
        job = SCRIPT_ASSISTANT_JOBS[job_id]
        rows = job["groups"][0]["rows"]
        self.assertEqual(call.call_args_list[1].kwargs["user"]["requested_line_count"], 3)
        self.assertIn("同時発話要件", call.call_args_list[0].kwargs["system"])
        self.assertNotIn("proposalCueId", rows[0])
        self.assertEqual(rows[1]["proposalCueId"], rows[2]["proposalCueId"])
        self.assertFalse(job["groups"][0]["warnings"])

        saved = {}
        with (
            patch("server.modules.project_repository.read_project", return_value=value),
            patch("server.modules.project_repository.write_project", side_effect=lambda next_project: saved.update({"project": next_project})),
        ):
            result = apply_script_assistant_proposal(ScriptAssistantApplyRequest(
                proposal_id=job["proposalId"], source_signature=job["sourceSignature"],
                accepted_group_ids=[job["groups"][0]["id"]],
            ))
        applied = result["scenes"][0]["lines"]
        self.assertNotIn("cueId", applied[0])
        self.assertEqual(applied[1]["cueId"], applied[2]["cueId"])
        self.assertEqual((applied[1]["startOffsetSeconds"], applied[2]["startOffsetSeconds"]), (0.0, 0.0))
        self.assertIs(saved["project"], result)

    def test_explicit_simultaneous_request_warns_when_the_model_omits_the_cue(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("target", "a")]})
        assistant_request = request(
            operation="rewrite", instruction="二人が同時発話で挨拶する", simultaneous_cues=True,
        )
        job_id = "script_assistant_job_missing_cue"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        generated = "\n".join([
            "A|おはよう||rate=1.0|gap=0.7|direction=明るく|cue=NONE",
            "B|こんにちは||rate=1.0|gap=0.7|direction=明るく|cue=NONE",
        ])
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", side_effect=["二人が同時に挨拶する。", generated]),
        ):
            run_script_assistant_job(job_id, assistant_request, value)
        self.assertIn("同時発話を提案内に構成できませんでした", SCRIPT_ASSISTANT_JOBS[job_id]["warnings"][0])

    def test_explicit_simultaneous_request_targets_the_first_contiguous_group(self) -> None:
        value = project(
            {"id": "scene-1", "title": "一", "lines": [
                line("sparse-1", "a"), line("anchor", "b"), line("sparse-2", "a"),
            ]},
            {"id": "scene-2", "title": "二", "lines": [line("contiguous", "b")]},
        )
        assistant_request = request(
            operation="rewrite", line_ids=["sparse-1", "sparse-2", "contiguous"],
            instruction="二人が同時発話で挨拶する", simultaneous_cues=True,
        )
        job_id = "script_assistant_job_multi_group_cue"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        routed: list[bool] = []

        def generate(*args, requires_simultaneous: bool):
            routed.append(requires_simultaneous)
            group = args[3]
            return {"id": group["id"], "warnings": []}

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._generate_group", side_effect=generate),
        ):
            run_script_assistant_job(job_id, assistant_request, value)
        self.assertEqual(routed, [False, True])
        self.assertEqual(SCRIPT_ASSISTANT_JOBS[job_id]["status"], "completed")

    def test_cast_composition_changes_only_profile_deviations_and_preserves_line_ownership(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [
            line("one", "a", "😊俺は絶対に謝らねえ", stageDirection="申し訳なさそうに",
                 speechRate=0.9, gapSeconds=0.4, cueId="cue", startOffsetSeconds=0.1,
                 takes=[{"id": "take", "audioUrl": ""}], selectedTakeId="take"),
            line("anchor", "b", "落ち着いて。", cueId="cue", startOffsetSeconds=0),
            line("three", "a", "承知しました。", stageDirection="静かに"),
        ]})
        value["characters"][0]["profile"] = "常に丁寧語を使い、非を認めたら素直に謝る。"
        value["characters"][0]["profileDetails"] = {"firstPerson": ["私"]}
        assistant_request = request(
            operation="cast-compose", line_ids=["one", "three"], character_ids=["a"],
            target_line_count=2, emoji_expressions=False, simultaneous_cues=False,
        )
        job_id = "script_assistant_job_cast_composition"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        generated = "\n".join([
            "R1|A|[EMOJI_1]申し訳ありません。私の誤りです。",
            "R2|A|承知しました。",
        ])
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", return_value=generated) as call,
        ):
            run_script_assistant_job(job_id, assistant_request, value)
        job = SCRIPT_ASSISTANT_JOBS[job_id]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["groups"][0]["rows"]), 1)
        proposal = job["groups"][0]["rows"][0]
        self.assertEqual((proposal["originalLineId"], proposal["characterId"]), ("one", "a"))
        self.assertEqual(proposal["text"], "😊申し訳ありません。私の誤りです。")
        self.assertEqual((proposal["stageDirection"], proposal["speechRate"], proposal["gapSeconds"]),
                         ("申し訳なさそうに", 0.9, 0.4))
        generation = call.call_args.kwargs
        self.assertIn("プロフィールから逸脱", generation["system"])
        self.assertEqual(generation["user"]["selected_casts"][0]["profile_details"], {"firstPerson": ["私"]})
        self.assertEqual(generation["user"]["original_target_rows"][0]["rewrite_id"], "R1")
        self.assertIn("[EMOJI_1]", generation["user"]["original_target_rows"][0]["text"])

        with (
            patch("server.modules.project_repository.read_project", return_value=value),
            patch("server.modules.project_repository.write_project"),
        ):
            result = apply_script_assistant_proposal(ScriptAssistantApplyRequest(
                proposal_id=job["proposalId"], source_signature=job["sourceSignature"],
                accepted_row_ids=[proposal["id"]],
            ))
        applied = result["scenes"][0]["lines"]
        self.assertEqual((applied[0]["id"], applied[0]["characterId"], applied[0]["text"]),
                         ("one", "a", "😊申し訳ありません。私の誤りです。"))
        self.assertEqual((applied[0]["stageDirection"], applied[0]["cueId"], applied[0]["startOffsetSeconds"]),
                         ("申し訳なさそうに", "cue", 0.1))
        self.assertEqual((applied[1]["id"], applied[1]["text"]), ("anchor", "落ち着いて。"))
        self.assertEqual((applied[2]["id"], applied[2]["text"]), ("three", "承知しました。"))

    def test_cast_composition_maps_a_partial_record_by_rewrite_id(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [
            line("one", "a", "問題ありません。"), line("two", "a", "俺に任せろ。"),
        ]})
        assistant_request = request(
            operation="cast-compose", line_ids=["one", "two"], character_ids=["a"], target_line_count=2,
        )
        job_id = "script_assistant_job_partial_cast_composition"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", return_value="R2|A|私にお任せください。"),
        ):
            run_script_assistant_job(job_id, assistant_request, value)
        group = SCRIPT_ASSISTANT_JOBS[job_id]["groups"][0]
        self.assertEqual(group["rows"][0]["originalLineId"], "two")
        self.assertIn("対象2行のうち1行を確認できました。", group["warnings"])

    def test_cast_composition_processes_large_scenes_in_ordered_batches(self) -> None:
        originals = [line(f"line-{index}", "a", f"元の台詞{index}") for index in range(1000)]
        value = project({"id": "scene-1", "title": "一", "lines": originals})
        assistant_request = request(
            operation="cast-compose", line_ids=[item["id"] for item in originals],
            character_ids=["a"], target_line_count=len(originals),
        )
        job_id = "script_assistant_job_batched_cast_composition"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        contexts: list[dict] = []

        def generate(*_args, **kwargs):
            user = kwargs["user"]
            contexts.append(user)
            target_rows = user["original_target_rows"]
            return "\n".join(
                f"{row['rewrite_id']}|A|{'変更後' if index == len(target_rows) - 1 else row['text']}"
                for index, row in enumerate(target_rows)
            )

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", side_effect=generate),
        ):
            run_script_assistant_job(job_id, assistant_request, value)
        group = SCRIPT_ASSISTANT_JOBS[job_id]["groups"][0]
        self.assertGreater(len(contexts), 1)
        flattened_ids = [
            row["rewrite_id"] for context in contexts for row in context["original_target_rows"]
        ]
        self.assertEqual(flattened_ids, [f"R{index}" for index in range(1, 1001)])
        self.assertEqual(contexts[1]["preceding_processed_rows"][-1]["text"], "変更後")
        self.assertEqual(
            [row["originalLineId"] for row in group["rows"]],
            [context["original_target_rows"][-1]["id"] for context in contexts],
        )
        self.assertEqual(group["warnings"], [])

    def test_cast_composition_preserves_source_emoji_when_the_model_drops_its_placeholder(self) -> None:
        self.assertEqual(
            restore_cast_composition_emojis("申し訳ありません。", "😊俺は悪くねえ。"),
            "😊申し訳ありません。",
        )

    def test_cast_composition_returns_an_empty_preview_when_every_line_already_fits(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("target", "a", "承知しました。")]})
        assistant_request = request(
            operation="cast-compose", character_ids=["a"], target_line_count=1,
        )
        job_id = "script_assistant_job_aligned_cast"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", return_value="R1|A|承知しました。"),
        ):
            run_script_assistant_job(job_id, assistant_request, value)
        group = SCRIPT_ASSISTANT_JOBS[job_id]["groups"][0]
        self.assertEqual(group["rows"], [])
        self.assertEqual(group["warnings"], ["キャスト設定から逸脱している提案対象はありませんでした。"])

    def test_job_keeps_a_partial_paraphrase_proposal(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("one", "a"), line("two", "b")]})
        job_id = "script_assistant_job_test"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        generated = "R1|A|別の表現です。||rate=1.1|gap=0.6|direction=静かに|cue=NONE"
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_jobs._call", return_value=generated),
        ):
            run_script_assistant_job(job_id, request(operation="paraphrase", line_ids=["one", "two"]), value)
        job = SCRIPT_ASSISTANT_JOBS[job_id]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(job["groups"][0]["rows"]), 1)
        self.assertEqual(job["groups"][0]["rows"][0]["originalLineId"], "one")
        self.assertTrue(job["groups"][0]["warnings"])

    def test_complete_rewrite_plans_from_original_but_generation_does_not_receive_it(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [
            line("before", "a", "待ち合わせに遅れた"), line("target", "b", "元の特徴的な台詞"),
            line("after", "a", "それなら急ごう"),
        ]})
        job_id = "script_assistant_job_rewrite_plan"
        SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        generated = "NORMAL|A|別の入口から話す。||rate=1.1|gap=0.6|direction=静かに|cue=NONE"
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
            patch("server.modules.script_assistant_fitting.context_limit", return_value=32768),
            patch("server.modules.script_assistant_jobs._call", side_effect=["別の会話経路で合流する。", generated]) as call,
        ):
            run_script_assistant_job(job_id, request(operation="rewrite", instruction="緊張感を強める"), value)
        plan_user = call.call_args_list[0].kwargs["user"]
        generation_user = call.call_args_list[1].kwargs["user"]
        plan_system = call.call_args_list[0].kwargs["system"]
        self.assertEqual(plan_user["original_target_rows"][0]["text"], "元の特徴的な台詞")
        self.assertEqual(plan_user["author_instruction"], "緊張感を強める")
        self.assertIn("守るべき事実と意図", plan_system)
        self.assertIn("別の会話経路", plan_system)
        self.assertIn("新しい不可逆な設定や唐突な事件を足さず", plan_system)
        self.assertNotIn("original_target_rows", generation_user)

    def test_complete_rewrite_accepts_a_truncated_plan_but_rejects_an_empty_plan(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("target", "a")]})
        generated = "NORMAL|A|新しい台詞。||rate=1.1|gap=0.6|direction=静かに|cue=NONE"
        for job_id, plan, expected in (("partial", "守る事実は約束。次に", "completed"), ("empty", "  ", "failed")):
            SCRIPT_ASSISTANT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
            calls = [plan, generated] if plan.strip() else [plan]
            with (
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/script-assistant-test")),
                patch("server.modules.script_assistant_jobs._call", side_effect=calls),
            ):
                run_script_assistant_job(job_id, request(operation="rewrite"), value)
            self.assertEqual(SCRIPT_ASSISTANT_JOBS[job_id]["status"], expected)
        self.assertIn("書き直し方針", SCRIPT_ASSISTANT_JOBS["empty"]["message"])

    def test_apply_preserves_identity_and_cue_but_deletes_takes_and_readings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            audio = media / "takes" / "old.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"wav")
            original = line("target", "a", enabled=False, cueId="cue", startOffsetSeconds=0.2,
                            pronunciations=[{"id": "p"}], selectedTakeId="take", takes=[{"id": "take", "audioUrl": "/media/takes/old.wav"}])
            sibling = line("sibling", "b", cueId="cue", startOffsetSeconds=0)
            value = project({"id": "scene-1", "title": "一", "lines": [original, sibling]})
            assistant_request = request(operation="paraphrase")
            signature = script_assistant_signature(value, assistant_request)
            proposal_id = "assistant_proposal_test"
            SCRIPT_ASSISTANT_PROPOSALS[proposal_id] = {
                "id": proposal_id, "sourceSignature": signature, "request": assistant_request.model_dump(),
                "groups": [{"id": "group", "sceneId": "scene-1", "atomic": False, "contiguous": True,
                            "insertIndex": 0, "targetLineIds": ["target"], "rows": [{
                                "id": "row", "originalLineId": "target", "characterId": "a", "text": "言い換え",
                                "stageDirection": "自然に", "speechRate": 1.1, "gapSeconds": 0.5,
                            }]}],
            }
            saved = {}
            with (
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.project_repository.read_project", return_value=value),
                patch("server.modules.project_repository.write_project", side_effect=lambda next_project: saved.update({"project": next_project})),
            ):
                result = apply_script_assistant_proposal(ScriptAssistantApplyRequest(
                    proposal_id=proposal_id, source_signature=signature, accepted_row_ids=["row"],
                ))
            rewritten = result["scenes"][0]["lines"][0]
            self.assertEqual((rewritten["id"], rewritten["text"], rewritten["enabled"]), ("target", "言い換え", False))
            self.assertEqual((rewritten["cueId"], rewritten["startOffsetSeconds"]), ("cue", 0.2))
            self.assertEqual((rewritten["takes"], rewritten["selectedTakeId"]), ([], None))
            self.assertNotIn("pronunciations", rewritten)
            self.assertFalse(audio.exists())
            self.assertIs(saved["project"], result)

    def test_apply_rejects_a_stale_script(self) -> None:
        value = project({"id": "scene-1", "title": "一", "lines": [line("target", "a")]})
        assistant_request = request()
        signature = script_assistant_signature(value, assistant_request)
        proposal_id = "assistant_proposal_stale"
        SCRIPT_ASSISTANT_PROPOSALS[proposal_id] = {"id": proposal_id, "sourceSignature": signature,
            "request": assistant_request.model_dump(), "groups": []}
        value["scenes"][0]["lines"][0]["text"] = "編集済み"
        with patch("server.modules.project_repository.read_project", return_value=value):
            with self.assertRaises(HTTPException) as raised:
                apply_script_assistant_proposal(ScriptAssistantApplyRequest(
                    proposal_id=proposal_id, source_signature=signature, accepted_row_ids=["row"],
                ))
        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()

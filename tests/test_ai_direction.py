from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from server.app import AiDirectionRequest, DRAFT_JOBS, DRAFT_JOBS_LOCK, run_ai_direction
from server.modules.ai_direction import _record_values
from server.modules.llm_emoji_policy import apply_llm_emoji_anchor_proposals, filter_llm_proposed_emojis


class AiDirectionTests(unittest.TestCase):
    def _request(self, **changes: object) -> AiDirectionRequest:
        values: dict[str, object] = {
            "base_url": "http://127.0.0.1:11434/v1",
            "model": "test-model",
            "line_ids": ["line-1"],
            "emoji_expressions": False,
            "speech_rate": False,
            "gap_seconds": False,
            "stage_direction": False,
            **changes,
        }
        return AiDirectionRequest(**values)

    def test_removals_are_mutually_exclusive_with_generation(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(emoji_expressions=True, remove_emoji_expressions=True)

    def test_emoji_direction_only_allows_server_side_insertions(self) -> None:
        source = "鼻からゆっくり息を吸ってください。"
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "😌@鼻から;🐢@ゆっくり", {"😌", "🐢"}),
            "😌鼻から🐢ゆっくり息を吸ってください。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "👃@から", {"👃"}),
            "鼻👃からゆっくり息を吸ってください。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals("そのまま、維持してください。", "😌@そのまま,維持", {"😌"}),
            "😌そのまま、維持してください。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals("一つ、二つ。一つ、二つ。", "🐢@一つ,二つ#2", {"🐢"}),
            "一つ、二つ。🐢一つ、二つ。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "☁️@鼻から;😌@ゆっくり", {"😌"}),
            "鼻から😌ゆっくり息を吸ってください。",
        )
        self.assertEqual(apply_llm_emoji_anchor_proposals(source, "☁️@鼻から", {"😌"}), source)
        self.assertIsNone(apply_llm_emoji_anchor_proposals(source, "😌@存在しない語句", {"😌"}))

    def test_emoji_direction_combines_and_caps_emojis_at_one_anchor(self) -> None:
        source = "その言葉を聞かせて。"
        allowed = {"🐢", "🥺", "😖", "⏩"}
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "🐢🥺😖@言葉", allowed),
            "その🐢🥺😖言葉を聞かせて。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "🐢🐢🥺@言葉", allowed),
            "その🐢🐢🥺言葉を聞かせて。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "🐢@言葉;🐢@言葉", allowed),
            "その🐢言葉を聞かせて。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "🐢🥺😖⏩@言葉", allowed),
            "その🐢🥺😖言葉を聞かせて。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals(source, "☁️🐢🥺😖@言葉", allowed),
            "その🐢🥺😖言葉を聞かせて。",
        )
        self.assertEqual(
            apply_llm_emoji_anchor_proposals("😌言葉を聞かせて。", "😌@言葉", {"😌"}),
            "😌言葉を聞かせて。",
        )

    def test_direct_draft_emoji_output_uses_the_same_three_emoji_cap(self) -> None:
        self.assertEqual(
            filter_llm_proposed_emojis("☁️🐢🥺😖⏩言葉", allowed={"🐢", "🥺", "😖", "⏩"}),
            "🐢🥺😖言葉",
        )

    def test_direction_recovers_misplaced_field_separators_without_splitting_emoji_insertions(self) -> None:
        self.assertEqual(
            _record_values(["emoji=😌@そのまま;rate=0.90", "gap=1.50", "direction=穏やかに"]),
            {"emoji": "😌@そのまま", "rate": "0.90", "gap": "1.50", "direction": "穏やかに"},
        )

    def test_emoji_direction_preserves_the_source_text_without_returning_it(self) -> None:
        project: dict[str, object] = {
            "scenes": [
                {
                    "lines": [
                        {
                            "id": "line-1",
                            "characterId": "cast-1",
                            "text": "こんにちは🍀",
                            "takes": [],
                        }
                    ]
                }
            ],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_emoji_insertion_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch(
                    "server.modules.llm_client.openai_stream_text_completion",
                    return_value="L1|emoji=🐢🥺😖@こんにちは|rate=0.90",
                ) as completion,
            ):
                run_ai_direction(
                    job_id, self._request(emoji_expressions=True, speech_rate=True, allowed_emojis=["🐢", "🥺", "😖"])
                )

            line = project["scenes"][0]["lines"][0]  # type: ignore[index]
            self.assertEqual(line["text"], "🐢🥺😖こんにちは🍀")  # type: ignore[index]
            self.assertEqual(line["speechRate"], 0.9)  # type: ignore[index]
            self.assertIn("Use only emoji, rate, gap, direction fields", completion.call_args.kwargs["system"])
            section_names = [next(iter(section)) for section in completion.call_args.kwargs["user"]["sections"]]
            self.assertEqual(section_names, ["request_settings", "participating_casts", "lines"])
            self.assertIn("低いrateでも急がせたい", completion.call_args.kwargs["system"])
            self.assertIn("📢は叫び・大声・強調を表すEMOJIではない", completion.call_args.kwargs["system"])
            self.assertIn("Use one EMOJI normally", completion.call_args.kwargs["system"])
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_emoji_direction_replaces_existing_expressions_only_when_overwriting(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "😌こんにちは。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_emoji_overwrite_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch("server.modules.llm_client.openai_stream_text_completion", return_value="L1|emoji=🐢@こんにちは"),
            ):
                run_ai_direction(
                    job_id, self._request(emoji_expressions=True, allowed_emojis=["🐢"], overwrite_existing=True)
                )
            self.assertEqual(project["scenes"][0]["lines"][0]["text"], "🐢こんにちは。")  # type: ignore[index]
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_emoji_direction_skips_existing_expressions_without_overwriting(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "😌こんにちは。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_emoji_skip_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch("server.modules.llm_client.openai_stream_text_completion", return_value="L1|emoji=🐢@こんにちは"),
            ):
                run_ai_direction(job_id, self._request(emoji_expressions=True, allowed_emojis=["🐢"]))
            self.assertEqual(project["scenes"][0]["lines"][0]["text"], "😌こんにちは。")  # type: ignore[index]
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_emoji_direction_accepts_a_line_without_an_emoji_insertion(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "短い返事です。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_optional_emoji_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch("server.modules.llm_client.openai_stream_text_completion", return_value="L1"),
            ):
                run_ai_direction(job_id, self._request(emoji_expressions=True, allowed_emojis=["😌"]))
            self.assertEqual(project["scenes"][0]["lines"][0]["text"], "短い返事です。")  # type: ignore[index]
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["status"], "completed")
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_direction_accepts_omitted_rate_and_gap_without_setting_them(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "……。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_optional_timing_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch(
                    "server.modules.llm_client.openai_stream_text_completion",
                    return_value="L1|direction=静かに間を置く",
                ),
            ):
                run_ai_direction(job_id, self._request(speech_rate=True, gap_seconds=True, stage_direction=True))
            line = project["scenes"][0]["lines"][0]  # type: ignore[index]
            self.assertEqual(line["stageDirection"], "静かに間を置く")  # type: ignore[index]
            self.assertNotIn("speechRate", line)  # type: ignore[arg-type]
            self.assertNotIn("gapSeconds", line)  # type: ignore[arg-type]
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_direction_rejects_only_a_negative_tts_caption_field(self) -> None:
        row = {"text": "切ない声で呼びかける", "stage": "既存のト書き"}
        request = self._request(speech_rate=True, stage_direction=True)
        from server.modules.ai_direction import _performance_patch

        patch = _performance_patch(request, row, {"rate": "0.92", "direction": "リバーブなしで切ない声"}, set())
        self.assertEqual(patch, {"speechRate": 0.92})

        accepted = _performance_patch(request, row, {"direction": "切ない声で静かに呼びかける"}, set())
        self.assertEqual(accepted["stageDirection"], "切ない声で静かに呼びかける")

    def test_direction_clamps_out_of_range_rate_without_retrying(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "急ぎます。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_rate_clamp_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch(
                    "server.modules.llm_client.openai_stream_text_completion", return_value="L1|rate=0.80"
                ) as completion,
            ):
                run_ai_direction(job_id, self._request(speech_rate=True, speech_rate_min=0.85, speech_rate_max=1.05))
            self.assertEqual(project["scenes"][0]["lines"][0]["speechRate"], 0.85)  # type: ignore[index]
            completion.assert_called_once()
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_direction_persists_the_apply_failure_with_its_stage(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "確認です。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_failure_log_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with TemporaryDirectory() as directory:
                debug_directory = Path(directory)
                with (
                    patch("server.modules.constants.LLM_DEBUG_ENABLED", True),
                    patch(
                        "server.modules.project_repository.read_project",
                        side_effect=[project, RuntimeError("project write conflict")],
                    ),
                    patch("server.modules.workspace.draft_debug_directory", return_value=debug_directory),
                    patch(
                        "server.modules.llm_client.openai_stream_text_completion",
                        return_value="L1|direction=自然に話す",
                    ),
                ):
                    run_ai_direction(job_id, self._request(stage_direction=True))
                failure = json.loads((debug_directory / "ai-direction-failure.json").read_text())
            self.assertEqual(failure["stage"], "演出の反映")
            self.assertEqual(failure["completedChunks"], 1)
            self.assertEqual(failure["errorType"], "RuntimeError")
            self.assertEqual(failure["error"], "project write conflict")
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_direction_keeps_existing_values_when_a_row_is_missing(self) -> None:
        project: dict[str, object] = {
            "scenes": [
                {
                    "lines": [
                        {"id": "line-1", "characterId": "cast-1", "text": "一行目です。", "takes": []},
                        {"id": "line-2", "characterId": "cast-1", "text": "二行目です。", "takes": []},
                    ]
                }
            ],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_partial_apply_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project") as write_project,
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch(
                    "server.modules.llm_client.openai_stream_text_completion",
                    return_value="L1|direction=自然に話す",
                ),
            ):
                run_ai_direction(job_id, self._request(line_ids=["line-1", "line-2"], stage_direction=True))
            lines = project["scenes"][0]["lines"]  # type: ignore[index]
            self.assertEqual(lines[0]["stageDirection"], "自然に話す")  # type: ignore[index]
            self.assertNotIn("stageDirection", lines[1])  # type: ignore[operator]
            write_project.assert_called_once_with(project)
            with DRAFT_JOBS_LOCK:
                job = DRAFT_JOBS[job_id]
                self.assertEqual(
                    (job["status"], job["performanceCompletedLines"], job["performanceTotalLines"]), ("completed", 2, 2)
                )
                self.assertEqual(job["message"], "AI演出を反映しました。")
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_direction_ignores_invalid_timing_without_retrying(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "一行目です。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_blank_timing_after_retries"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project") as write_project,
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch(
                    "server.modules.llm_client.openai_stream_text_completion",
                    return_value="L1|rate=abc|gap=abc",
                ) as completion,
            ):
                run_ai_direction(
                    job_id,
                    self._request(line_ids=["line-1"], speech_rate=True, gap_seconds=True, stage_direction=False),
                )
            line = project["scenes"][0]["lines"][0]  # type: ignore[index]
            self.assertNotIn("speechRate", line)  # type: ignore[operator]
            self.assertNotIn("gapSeconds", line)  # type: ignore[operator]
            self.assertNotIn("stageDirection", line)  # type: ignore[arg-type]
            completion.assert_called_once()
            write_project.assert_called_once_with(project)
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["status"], "completed")
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_direction_does_not_retry_transport_failures(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{"id": "line-1", "characterId": "cast-1", "text": "試験です。", "takes": []}]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_all_retries_failed"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project") as write_project,
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch(
                    "server.modules.llm_client.openai_stream_text_completion",
                    side_effect=RuntimeError("temporary failure"),
                ) as completion,
            ):
                run_ai_direction(job_id, self._request(line_ids=["line-1"], speech_rate=True, gap_seconds=True))
            completion.assert_called_once()
            write_project.assert_not_called()
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["status"], "failed")
                self.assertEqual(DRAFT_JOBS[job_id]["error"], "temporary failure")
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

    def test_removals_keep_regular_emoji_and_skip_llm(self) -> None:
        project: dict[str, object] = {
            "scenes": [
                {
                    "lines": [
                        {
                            "id": "line-1",
                            "characterId": "cast-1",
                            "text": "通常の絵文字🍀と😭表情EMOJI",
                            "speechRate": 1.15,
                            "gapSeconds": 1.2,
                            "stageDirection": "小声で話す",
                            "takes": [{"id": "take-1"}],
                        }
                    ],
                }
            ],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        job_id = "ai_direction_removal_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project") as write_project,
                patch("server.modules.llm_client.openai_stream_text_completion") as completion,
            ):
                run_ai_direction(
                    job_id,
                    self._request(
                        remove_emoji_expressions=True,
                        remove_speech_rate=True,
                        remove_gap_seconds=True,
                        remove_stage_direction=True,
                    ),
                )

            line = project["scenes"][0]["lines"][0]  # type: ignore[index]
            self.assertEqual(line["text"], "通常の絵文字🍀と表情EMOJI")  # type: ignore[index]
            self.assertNotIn("speechRate", line)  # type: ignore[arg-type]
            self.assertNotIn("gapSeconds", line)  # type: ignore[arg-type]
            self.assertNotIn("stageDirection", line)  # type: ignore[arg-type]
            completion.assert_not_called()
            write_project.assert_called_once_with(project)
            with DRAFT_JOBS_LOCK:
                self.assertEqual(DRAFT_JOBS[job_id]["status"], "completed")
                self.assertEqual(DRAFT_JOBS[job_id]["renderLineIds"], ["line-1"])
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)

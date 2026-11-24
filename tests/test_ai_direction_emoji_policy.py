from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import AiDirectionRequest, DRAFT_JOBS, DRAFT_JOBS_LOCK, run_ai_direction


class AiDirectionEmojiPolicyTests(unittest.TestCase):
    def test_cast_setting_blocks_emoji_for_one_cast_and_preserves_other_fields(self) -> None:
        from server.modules.ai_direction import _performance_patch
        from server.modules.ai_direction_prompt import build_direction_prompt

        request = AiDirectionRequest(
            line_ids=["line-a", "line-b"], emoji_expressions=True,
            cast_settings={"cast-a": {"emoji_expressions": True}, "cast-b": {"emoji_expressions": False}},
            allowed_emojis=["😊"],
        )
        rows = [
            {"alias": "L1", "id": "line-a", "character_id": "cast-a", "name": "彩", "text": "おはよう。", "rate": "未設定", "gap": "未設定", "stage": "", "emoji_allowed": True},
            {"alias": "L2", "id": "line-b", "character_id": "cast-b", "name": "葵", "text": "おはよう。", "rate": "未設定", "gap": "未設定", "stage": "", "emoji_allowed": False},
        ]
        _, prompt = build_direction_prompt(request, rows, [], [])
        self.assertIn("表情EMOJI=禁止", str(prompt))
        values = {"emoji": "😊@おはよう", "direction": "明るく"}
        allowed = {"😊"}
        enabled = _performance_patch(request, rows[0], values, allowed)
        disabled = _performance_patch(request, rows[1], values, allowed)
        self.assertEqual(enabled["text"], "😊おはよう。")
        self.assertNotIn("text", disabled)
        self.assertEqual(disabled["stageDirection"], "明るく")

    def test_ai_direction_never_proposes_or_accepts_muffled_emoji(self) -> None:
        project: dict[str, object] = {
            "scenes": [{"lines": [{
                "id": "line-1", "characterId": "cast-1", "text": "声が出せない。", "takes": [],
            }]}],
            "characters": [{"id": "cast-1", "name": "彩"}],
        }
        request = AiDirectionRequest(
            base_url="http://127.0.0.1:11434/v1",
            model="test-model",
            line_ids=["line-1"],
            emoji_expressions=True,
            speech_rate=False,
            gap_seconds=False,
            stage_direction=False,
            allowed_emojis=["🤐"],
        )
        job_id = "ai_direction_muffled_effect_test"
        with DRAFT_JOBS_LOCK:
            DRAFT_JOBS[job_id] = {"id": job_id, "status": "planning", "cancelRequested": False}
        try:
            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/ai-direction-debug")),
                patch(
                    "server.modules.llm_client.openai_stream_text_completion",
                    return_value="L1|emoji=🤐@声が出せない",
                ) as completion,
            ):
                run_ai_direction(job_id, request)
            line = project["scenes"][0]["lines"][0]  # type: ignore[index]
            self.assertEqual(line["text"], "声が出せない。")  # type: ignore[index]
            settings = completion.call_args.kwargs["user"]["sections"][0]["request_settings"]
            self.assertIn("許可EMOJI: なし", settings)
        finally:
            with DRAFT_JOBS_LOCK:
                DRAFT_JOBS.pop(job_id, None)


if __name__ == "__main__":
    unittest.main()

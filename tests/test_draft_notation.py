from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from server.app import DraftRequest, normalize_draft_notation


def request() -> DraftRequest:
    return DraftRequest(
        base_url="http://127.0.0.1:9999/v1",
        model="test-model",
        character_ids=["cinnamon"],
        target_minutes=1,
        theme="表記検査です。",
    )


def chapters(text: str) -> list[dict]:
    return [{"chapter": {"title": "一章"}, "dialogue": {"lines": [{"line_id": "C001L001", "character_id": "cinnamon", "text": text}]}, "spoken": len(text), "discarded_duplicates": 0}]


class DraftNotationTests(unittest.TestCase):
    def test_pronoun_and_default_honorific_join_is_locally_repaired(self) -> None:
        source = chapters("あなたさん、少し待ってください。")
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value="L1|0|あなたさん|あなた") as completion,
        ):
            result = normalize_draft_notation(
                request(), job_id="test-job", drafted_chapters=source,
                characters=[{"id": "cinnamon", "profileDetails": {
                    "secondPerson": ["あなた"], "defaultHonorific": "さん",
                }}],
                cast_alias_by_id={"cinnamon": "A"}, token_budget=2048, debug_directory=Path("/tmp"),
            )
        self.assertEqual(result[0]["dialogue"]["lines"][0]["text"], "あなた、少し待ってください。")
        self.assertEqual(completion.call_args.kwargs["user"]["candidates"][0]["kind"], "address")

    def test_explicit_relation_address_preserves_pronoun_honorific_join(self) -> None:
        source = chapters("あなたさん、少し待ってください。")
        with patch("server.modules.llm_client.openai_stream_text_completion") as completion:
            result = normalize_draft_notation(
                request(), job_id="test-job", drafted_chapters=source,
                characters=[{"id": "cinnamon", "profileDetails": {
                    "secondPerson": ["あなた"], "defaultHonorific": "さん",
                    "castRelations": {"other": {"address": "あなたさん"}},
                }}],
                cast_alias_by_id={"cinnamon": "A"}, token_budget=2048, debug_directory=Path("/tmp"),
            )
        self.assertEqual(result[0]["dialogue"]["lines"][0]["text"], "あなたさん、少し待ってください。")
        completion.assert_not_called()

    def test_safe_simplified_glyphs_are_local_and_quotes_are_protected(self) -> None:
        source = chapters("纱良は帰还した。『纱』は台詞の引用です。")
        with patch("server.modules.llm_client.openai_stream_text_completion") as completion:
            result = normalize_draft_notation(
                request(), job_id="test-job", drafted_chapters=source,
                characters=[{"id": "cinnamon", "profileDetails": {}}], cast_alias_by_id={"cinnamon": "A"},
                token_budget=2048, debug_directory=Path("/tmp"),
            )
        self.assertEqual(result[0]["dialogue"]["lines"][0]["text"], "紗良は帰還した。『纱』は台詞の引用です。")
        completion.assert_not_called()

    def test_one_small_request_applies_only_a_valid_pronoun_and_contextual_glyph_patch(self) -> None:
        source = chapters("这、あんたの番だよ。")
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value="L1|0|这|此\nL1|2|あんた|あなた") as completion,
        ):
            result = normalize_draft_notation(
                request(), job_id="test-job", drafted_chapters=source,
                characters=[{"id": "cinnamon", "profileDetails": {"secondPerson": ["あなた"]}}],
                cast_alias_by_id={"cinnamon": "A"}, token_budget=2048, debug_directory=Path("/tmp"),
            )
        self.assertEqual(result[0]["dialogue"]["lines"][0]["text"], "此、あなたの番だよ。")
        candidates = completion.call_args.kwargs["user"]["candidates"]
        self.assertEqual({item["expected"] for item in candidates}, {"这", "あんた"})

    def test_pronoun_exclusion_candidates(self) -> None:
        for text in (
            "自分は大事な台詞だけ言っておく。",
            "うちは今夜の予定を決める。",
            "我は後で戻る。",
            "君はもう一回言って。",
        ):
            with self.subTest(text=text):
                source = chapters(text)
                with (
                    patch("server.modules.draft_job_state.begin_draft_llm_call"),
                    patch("server.modules.llm_client.openai_stream_text_completion", return_value="") as completion,
                ):
                    result = normalize_draft_notation(
                        request(), job_id="test-job", drafted_chapters=source,
                        characters=[{"id": "cinnamon", "profileDetails": {"secondPerson": ["あなた"]}}],
                        cast_alias_by_id={"cinnamon": "A"}, token_budget=2048, debug_directory=Path("/tmp"),
                    )
                self.assertEqual(result[0]["dialogue"]["lines"][0]["text"], text)
                completion.assert_not_called()

    def test_quotes_repetition_and_invalid_patches_leave_the_original_text(self) -> None:
        source = chapters("僕が何とかする！だって？ あんたは待ってて。")
        with (
            patch("server.modules.draft_job_state.begin_draft_llm_call"),
            patch("server.modules.llm_client.openai_stream_text_completion", return_value="L1|99|あんた|あなた"),
        ):
            result = normalize_draft_notation(
                request(), job_id="test-job", drafted_chapters=source,
                characters=[{"id": "cinnamon", "profileDetails": {"firstPerson": ["私"], "secondPerson": ["あなた"]}}],
                cast_alias_by_id={"cinnamon": "A"}, token_budget=2048, debug_directory=Path("/tmp"),
            )
        self.assertEqual(result[0]["dialogue"]["lines"][0]["text"], source[0]["dialogue"]["lines"][0]["text"])

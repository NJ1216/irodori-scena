from __future__ import annotations

import json
import unittest
from pathlib import Path

from server.modules.llm_response_formatters import normalize_suggested_theme


class ThemeResponseFormatterTests(unittest.TestCase):
    def test_accepts_long_and_short_paragraphs(self) -> None:
        long_theme = "古い劇場を舞台に、閉館前日の出来事を描く。" * 20
        short_theme = "雨宿りで再会し、昔の誤解を解く。"
        self.assertGreaterEqual(len(long_theme), 300)
        self.assertEqual(normalize_suggested_theme(long_theme), long_theme)
        self.assertEqual(normalize_suggested_theme(short_theme), short_theme)

    def test_recovers_transport_wrappers(self) -> None:
        paragraph = "港の倉庫で失われた手紙を探し、夜明けまでに持ち主へ返す。"
        self.assertEqual(normalize_suggested_theme(f"\ufeff```text\n{paragraph}\n```"), paragraph)
        self.assertEqual(normalize_suggested_theme(json.dumps(paragraph, ensure_ascii=False)), paragraph)
        for key in ("theme", "proposal", "content"):
            wrapped = json.dumps({key: paragraph}, ensure_ascii=False)
            self.assertEqual(normalize_suggested_theme(wrapped), paragraph)

    def test_recovers_final_text_from_leaked_harmony_transport(self) -> None:
        paragraph = "舞台は東京のネットカフェ。二人は追跡をかわし、失われたデータを取り戻す。"
        leaked = (
            "<|channel|> analysis<|message|> Need 300-400 Japanese characters, single paragraph."
            "<|start|> assistant<|channel|> final<|message|> "
            f"{paragraph}<|end|>"
        )
        self.assertEqual(normalize_suggested_theme(leaked), paragraph)

    def test_preserves_token_like_text_without_an_explicit_final_message(self) -> None:
        text = "作中の端末に<|channel|>という未知の文字列が表示され、調査が始まる。"
        self.assertEqual(normalize_suggested_theme(text), text)

    def test_accepts_saved_gemma4_response_fixture(self) -> None:
        fixture = Path("tests/fixtures/gemma4-26b-mlx-theme-suggestion.txt").read_text(encoding="utf-8")
        normalized = normalize_suggested_theme(fixture)
        self.assertIsNotNone(normalized)
        self.assertIn("商店街", normalized)


if __name__ == "__main__":
    unittest.main()

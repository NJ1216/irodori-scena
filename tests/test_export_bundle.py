from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server.app import (
    ExportStartRequest,
    csv_field,
    line_base_name,
    normalized_file_key,
    srt_text,
    subtitle_export_text,
    truncate_file_name,
)


class ExportBundleFormattingTests(unittest.TestCase):
    def test_naming_omits_unused_separators_and_allows_duplicates(self) -> None:
        self.assertEqual(line_base_name(1, "桜", "こんにちは", ["sequence", "none", "cast"]), "001_桜")
        self.assertEqual(line_base_name(2, "桜", "本文", ["cast", "cast", "text"]), "桜_桜_本文")
        self.assertEqual(line_base_name(3, "山田 太郎", "本文", ["sequence", "cast", "none"]), "003_山田太郎")

    def test_filename_is_shortened_on_unicode_boundaries(self) -> None:
        name = truncate_file_name("声" * 200, "wav")
        self.assertLessEqual(len(name.encode("utf-8")), 255)
        self.assertTrue(name.endswith(".wav"))

    def test_normalized_collision_key_handles_unicode_and_case(self) -> None:
        self.assertEqual(normalized_file_key("É.WAV"), normalized_file_key("E\u0301.wav"))

    def test_csv_fields_quote_delimiter_newline_and_quote(self) -> None:
        self.assertEqual(csv_field("a,b", ","), '"a,b"')
        self.assertEqual(csv_field('a"b', "\t"), '"a""b"')
        self.assertEqual(csv_field("a\nb", "\t"), '"a\nb"')

    def test_srt_uses_millisecond_timestamps(self) -> None:
        self.assertEqual(srt_text([("本文", 0, 1.234)]), "1\n00:00:00,000 --> 00:00:01,234\n本文\n")

    def test_development_subtitle_can_preserve_the_line_text_with_emoji(self) -> None:
        item = SimpleNamespace(line={"text": "🤔これは本当？"}, text="これは本当？")
        self.assertEqual(subtitle_export_text(item, False), "これは本当？")
        self.assertEqual(subtitle_export_text(item, True), "🤔これは本当？")

    def test_emoji_subtitle_option_is_rejected_outside_development(self) -> None:
        payload = {"mode": "bundle", "destinationDir": "/tmp", "formats": ["subtitle_txt"], "subtitleIncludeEmoji": True}
        with patch("server.modules.constants.DEVELOPMENT_MODE_ENABLED", False), self.assertRaises(ValueError):
            ExportStartRequest(**payload)
        with patch("server.modules.constants.DEVELOPMENT_MODE_ENABLED", True):
            self.assertTrue(ExportStartRequest(**payload).subtitle_include_emoji)

    def test_bundle_validation_rejects_empty_formats_and_names(self) -> None:
        with self.assertRaises(ValueError):
            ExportStartRequest(mode="bundle", destinationDir="/tmp", formats=[])
        with self.assertRaises(ValueError):
            ExportStartRequest(mode="bundle", destinationDir="/tmp", formats=["wav"], naming=["none"] * 3)

    def test_joined_bundle_accepts_srt(self) -> None:
        request = ExportStartRequest(
            mode="bundle", destinationDir="/tmp", layout="joined", formats=["wav", "srt"],
        )
        self.assertEqual(request.formats, ["wav", "srt"])

    def test_lab_requires_split_wav(self) -> None:
        with self.assertRaises(ValueError):
            ExportStartRequest(mode="bundle", destinationDir="/tmp", layout="joined", formats=["wav", "lab"])
        with self.assertRaises(ValueError):
            ExportStartRequest(mode="bundle", destinationDir="/tmp", layout="split", formats=["lab"])
        request = ExportStartRequest(mode="bundle", destinationDir="/tmp", layout="split", formats=["wav", "lab"])
        self.assertEqual(request.formats, ["wav", "lab"])


if __name__ == "__main__":
    unittest.main()

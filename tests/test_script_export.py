from __future__ import annotations

import unittest

from server.modules.project_routes import _script_text


class ScriptExportTests(unittest.TestCase):
    def test_text_export_contains_context_and_skips_disabled_lines(self) -> None:
        project = {
            "characters": [{"id": "a", "name": "彩"}],
            "scriptCastContexts": {"a": {"role": "案内役", "description": "落ち着いて旅人を迎える。"}},
            "scenes": [{"title": "導入", "lines": [
                {"characterId": "a", "text": "こんにちは", "stageDirection": "穏やかに"},
                {"characterId": "a", "text": "除外", "stageDirection": "", "enabled": False},
            ]}],
        }
        text = _script_text(project)
        self.assertIn("彩｜役割: 案内役", text)
        self.assertIn("人物紹介: 落ち着いて旅人を迎える。", text)
        self.assertIn("0001 彩\n（穏やかに）\nこんにちは", text)
        self.assertNotIn("除外", text)

    def test_text_export_reads_legacy_cast_setting_as_description(self) -> None:
        project = {
            "characters": [{"id": "a", "name": "彩"}],
            "scriptCastContexts": {"a": {"role": "案内役", "setting": "静かに導く"}},
            "scenes": [{"title": "導入", "lines": [{"characterId": "a", "text": "こんにちは"}]}],
        }
        self.assertIn("人物紹介: 静かに導く", _script_text(project))


if __name__ == "__main__":
    unittest.main()

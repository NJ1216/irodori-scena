import scena_test_isolation  # noqa: F401
import unittest

from fastapi import HTTPException

from server.app import app as _app  # noqa: F401
from server.modules.line_split import split_dialogue_line


class LineSplitTests(unittest.TestCase):
    def test_openapi_exposes_optional_split_fields(self) -> None:
        properties = _app.openapi()["components"]["schemas"]["InsertLineRequest"]["properties"]
        self.assertIn("split_line_id", properties)
        self.assertIn("split_offset", properties)

    def test_middle_split_inherits_performance_but_not_seed_or_take(self) -> None:
        scene = {
            "lines": [
                {
                    "id": "source",
                    "characterId": "cast",
                    "text": "前半😊後半",
                    "pronunciations": [
                        {"id": "before", "start": 0, "end": 2, "text": "前半", "reading": "ぜんはん"},
                        {"id": "after", "start": 3, "end": 5, "text": "後半", "reading": "こうはん"},
                    ],
                    "stageDirection": "強く",
                    "speechRate": 1.2,
                    "gapSeconds": 0.4,
                    "textCfg": 3.1,
                    "voiceCfg": 5.2,
                    "captionCfg": 4.3,
                    "fixedSeed": 10,
                    "manualSeed": 11,
                    "takes": [{"id": "take"}],
                    "selectedTakeId": "take",
                }
            ]
        }

        created = split_dialogue_line(scene, "source", 3, "created")

        self.assertEqual(scene["lines"][0]["text"], "前半😊")
        self.assertIsNone(scene["lines"][0]["selectedTakeId"])
        self.assertEqual(created["text"], "後半")
        self.assertEqual(
            created["pronunciations"], [{"id": "after", "start": 0, "end": 2, "text": "後半", "reading": "こうはん"}]
        )
        self.assertEqual(
            {key: created[key] for key in ("speechRate", "gapSeconds", "textCfg", "voiceCfg", "captionCfg")},
            {"speechRate": 1.2, "gapSeconds": 0.4, "textCfg": 3.1, "voiceCfg": 5.2, "captionCfg": 4.3},
        )
        self.assertTrue(all(key not in created for key in ("fixedSeed", "manualSeed")))
        self.assertEqual(created["takes"], [])

    def test_end_split_creates_default_blank_line(self) -> None:
        source = {
            "id": "source",
            "characterId": "cast",
            "text": "文末",
            "speechRate": 1.2,
            "gapSeconds": 0.4,
            "textCfg": 3.1,
            "fixedSeed": 10,
            "takes": [],
            "selectedTakeId": None,
        }
        scene = {"lines": [source]}

        created = split_dialogue_line(scene, "source", 2, "created")

        self.assertEqual(created["text"], "")
        self.assertTrue(
            all(
                key not in created
                for key in ("speechRate", "gapSeconds", "textCfg", "voiceCfg", "captionCfg", "fixedSeed", "manualSeed")
            )
        )

    def test_rejects_offset_beyond_unicode_code_points(self) -> None:
        scene = {"lines": [{"id": "source", "characterId": "cast", "text": "😊", "takes": [], "selectedTakeId": None}]}
        with self.assertRaises(HTTPException) as raised:
            split_dialogue_line(scene, "source", 2, "created")
        self.assertEqual(raised.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()

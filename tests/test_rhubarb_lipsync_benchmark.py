import importlib.util
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "tools" / "rhubarb_lipsync_benchmark.py"
SPEC = importlib.util.spec_from_file_location("rhubarb_lipsync_benchmark", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class RhubarbLipSyncBenchmarkTest(unittest.TestCase):
    def test_selects_fixed_unique_quotas_deterministically(self) -> None:
        texts = {
            "ordinary": [f"通常の台詞{index}" for index in range(8)],
            "sibilants": [f"さしすせそ{index}" for index in range(4)],
            "closed_mouth": [f"まみむめも{index}" for index in range(4)],
            "laughter_repetition": [f"あはは{index}" for index in range(5)],
            "emoji_nonverbal": [f"😮‍💨ふぅ{index}" for index in range(5)],
            "long_pause": [f"待って…………{index}" for index in range(4)],
        }
        candidates = []
        for category, values in texts.items():
            for index, text in enumerate(values):
                key = f"{category}-{index}"
                candidates.append(MODULE.Sample("", key, f"take-{key}", text, Path(f"{key}.wav")))
        selected = MODULE.select_corpus(candidates)
        reversed_selected = MODULE.select_corpus(list(reversed(candidates)))
        self.assertEqual([sample.key for sample in selected], [sample.key for sample in reversed_selected])
        self.assertEqual(len({sample.key for sample in selected}), 30)
        self.assertEqual(
            {category: sum(sample.category == category for sample in selected) for category in MODULE.CATEGORY_QUOTAS},
            MODULE.CATEGORY_QUOTAS,
        )

    def test_maps_shapes_and_fills_rounded_timeline(self) -> None:
        cues = MODULE.parse_mouth_cues({
            "mouthCues": [
                {"start": 0.01, "end": 0.1, "value": "A"},
                {"start": 0.1, "end": 0.2, "value": "B"},
                {"start": 0.20000001, "end": 0.3, "value": "C"},
                {"start": 0.3, "end": 0.4, "value": "D"},
                {"start": 0.4, "end": 0.5, "value": "E"},
                {"start": 0.5, "end": 0.6, "value": "F"},
                {"start": 0.6, "end": 0.61, "value": "X"},
            ]
        })
        rows = MODULE.cues_to_lab(cues, 0.7)
        self.assertEqual(rows[0], (0, 100_000, "pau"))
        self.assertEqual([row[2] for row in rows], ["pau", "N", "i", "e", "a", "o", "u", "pau"])
        self.assertEqual(rows[-1][1], 7_000_000)
        self.assertTrue(all(left[1] == right[0] for left, right in zip(rows, rows[1:])))

    def test_rejects_overlapping_or_unknown_cues(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-overlapping"):
            MODULE.parse_mouth_cues({"mouthCues": [
                {"start": 0, "end": 0.2, "value": "A"}, {"start": 0.1, "end": 0.3, "value": "B"}
            ]})
        with self.assertRaisesRegex(ValueError, "unsupported"):
            MODULE.parse_mouth_cues({"mouthCues": [{"start": 0, "end": 0.2, "value": "G"}]})

    def test_preview_contains_audio_synced_mouth_animation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wav = Path(raw) / "take.wav"
            with wave.open(str(wav), "wb") as output:
                output.setparams((1, 2, 48_000, 0, "NONE", "not compressed"))
                output.writeframes(b"\0\0" * 480)
            sample = MODULE.Sample("ordinary", "line", "take", "確認用の台詞", wav)
            record = {"key": sample.key, "lab": [(0, 50_000, "N"), (50_000, 100_000, "a")]}
            preview = MODULE.preview_html([sample], [record])
            self.assertIn("data:audio/wav;base64,", preview)
            self.assertIn("class=\"mouth pau\"", preview)
            self.assertIn("requestAnimationFrame", preview)
            self.assertIn("文字位置は推定せず", preview)

    def test_loads_only_available_selected_project_take(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            project = Path(raw) / "sample.scena"
            wav = project / "media" / "takes" / "line" / "take.wav"
            wav.parent.mkdir(parents=True)
            with wave.open(str(wav), "wb") as output:
                output.setparams((1, 2, 48_000, 0, "NONE", "not compressed"))
                output.writeframes(b"\0\0" * 480)
            payload = {"scenes": [{"lines": [{
                "id": "line", "text": "本文", "selectedTakeId": "take",
                "takes": [{"id": "take", "audioUrl": "/media/takes/line/take.wav", "renderedText": "生成本文"}],
            }, {"id": "missing", "selectedTakeId": "none", "takes": []}]}]}
            (project / "project.json").write_text(json.dumps(payload), encoding="utf-8")
            samples = MODULE.load_selected_takes(project)
            self.assertEqual([(sample.line_id, sample.text) for sample in samples], [("line", "生成本文")])


if __name__ == "__main__":
    unittest.main()

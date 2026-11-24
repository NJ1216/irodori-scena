from __future__ import annotations

from pathlib import Path
import unittest

from fastapi import HTTPException
from server.modules.voice_design_generation import generate_candidate_clips


class Recorder:
    def __init__(self, durations: dict[str, float]) -> None:
        self.durations = durations
        self.calls: list[dict[str, object]] = []
        self.discarded: list[Path] = []

    def generate(self, *, output: Path, seed: int, num_candidates: int, **settings: object) -> list[Path]:
        self.calls.append({"output": output, "seed": seed, "num_candidates": num_candidates, **settings})
        if num_candidates == 1:
            return [output]
        return [output.with_name(f"{output.stem}_{index:03d}.wav") for index in range(1, num_candidates + 1)]

    def measure(self, path: Path) -> float:
        duration = self.durations.get(path.name, 5.0)
        if duration > 30.0:
            raise HTTPException(status_code=422, detail={"code": "voice_design_clip_too_long", "message": "x"})
        return duration

    def discard(self, paths: list[Path]) -> None:
        self.discarded.extend(paths)

    def run(self, count: int) -> list[tuple[Path, float]]:
        return generate_candidate_clips(
            self.generate, self.measure, self.discard, output=Path("/m/batch.wav"), seed=100, count=count, text="t"
        )


class GenerateCandidateClipsTests(unittest.TestCase):
    def test_generates_the_first_candidate_alone_then_the_rest_with_following_seeds(self) -> None:
        recorder = Recorder({})
        clips = recorder.run(3)
        self.assertEqual([(call["seed"], call["num_candidates"]) for call in recorder.calls], [(100, 1), (101, 2)])
        self.assertEqual([call["text"] for call in recorder.calls], ["t", "t"])
        self.assertEqual([path.name for path, _ in clips], ["batch_001.wav", "batch_rest_001.wav", "batch_rest_002.wav"])
        self.assertEqual([duration for _, duration in clips], [5.0, 5.0, 5.0])
        self.assertEqual(recorder.discarded, [])

    def test_a_single_candidate_needs_one_generation(self) -> None:
        recorder = Recorder({})
        self.assertEqual(len(recorder.run(1)), 1)
        self.assertEqual(len(recorder.calls), 1)

    def test_a_first_candidate_at_the_ceiling_asks_to_shorten_the_line_and_skips_the_rest(self) -> None:
        recorder = Recorder({"batch_001.wav": 29.9})
        with self.assertRaises(HTTPException) as raised:
            recorder.run(10)
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(raised.exception.detail["code"], "voice_design_sample_too_long")
        self.assertIn("試聴台詞を短く", raised.exception.detail["message"])
        self.assertEqual(len(recorder.calls), 1)
        self.assertEqual([path.name for path in recorder.discarded], ["batch_001.wav"])

    def test_a_line_just_under_the_ceiling_is_kept(self) -> None:
        recorder = Recorder({"batch_001.wav": 29.7})
        self.assertEqual(recorder.run(1)[0][1], 29.7)

    def test_a_rejected_later_clip_discards_every_generated_wav(self) -> None:
        recorder = Recorder({"batch_rest_002.wav": 31.0})
        with self.assertRaises(HTTPException):
            recorder.run(3)
        self.assertEqual(
            [path.name for path in recorder.discarded], ["batch_001.wav", "batch_rest_001.wav", "batch_rest_002.wav"]
        )


if __name__ == "__main__":
    unittest.main()

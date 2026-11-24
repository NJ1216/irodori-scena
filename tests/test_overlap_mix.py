from __future__ import annotations

import unittest
import tempfile
import json
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from server.app import (
    OVERLAP_ALGORITHM_VERSION,
    TRUE_PEAK_LIMIT,
    effective_unit_starts,
    overlap_signature,
    prepare_overlap_boundaries,
    render_overlap,
)
from tools.pcm_analysis import decode_pcm as _decode_pcm
from tests.audio_overlap_reference import (
    mix as reference_mix,
    render as reference_render,
    true_peak as reference_true_peak,
    write_pcm16 as reference_write,
)


class OverlapMixTests(unittest.TestCase):
    def test_cached_boundary_gain_matches_the_float32_reference_for_every_width(self) -> None:
        from server.modules.overlap_mix import cached_overlap_boundary_gain

        def reference(output, following, overlap_frames, post_roll_frames):
            window = min(post_roll_frames + 1, 32)
            mixed_all, _ = _decode_pcm(output)
            following_all, _ = _decode_pcm(following)
            mixed = mixed_all[max(0, len(mixed_all) - window):]
            start = max(0, overlap_frames + post_roll_frames - window)
            source_window = following_all[start:start + window]
            for offset in range(1, window + 1):
                if offset > len(source_window) or offset > len(mixed):
                    continue
                source = source_window[-offset]
                denominator = float(source @ source)
                if denominator > 1e-8:
                    return max(0.0, min(1.0, float(mixed[-offset] @ source) / denominator))
            return 1.0

        rng = np.random.default_rng(7)
        with tempfile.TemporaryDirectory() as directory:
            for width in (1, 2, 3, 4):
                for channels in (1, 2):
                    paths = []
                    for name, frames in (("mixed", 400), ("following", 300)):
                        path = Path(directory) / f"{name}-{width}-{channels}.wav"
                        raw = rng.integers(0, 256, size=frames * channels * width, dtype=np.uint8).tobytes()
                        with wave.open(str(path), "wb") as writer:
                            writer.setnchannels(channels)
                            writer.setsampwidth(width)
                            writer.setframerate(48_000)
                            writer.writeframes(raw)
                        paths.append(path)
                    for post_roll in (0, 5, 40):
                        expected = reference(paths[0], paths[1], 200, post_roll)
                        actual = cached_overlap_boundary_gain(paths[0], paths[1], 200, post_roll)
                        self.assertAlmostEqual(actual, expected, places=5, msg=(width, channels, post_roll))

    def test_project_plan_reads_each_of_244_wav_headers_once(self) -> None:
        lines = [
            {
                "id": f"line-{index}",
                "gapSeconds": -0.5 if index < 243 else 0,
                "selectedTakeId": f"take-{index}",
                "takes": [{"id": f"take-{index}", "audioUrl": f"/media/take-{index}.wav"}],
            }
            for index in range(244)
        ]
        project = {"settings": {"lineGap": 0.7}, "scenes": [{"id": "scene", "lines": lines}]}
        header_reads = 0

        class Header:
            def __enter__(self):
                nonlocal header_reads
                header_reads += 1
                return self

            def __exit__(self, *_args):
                return None

            def getnframes(self):
                return 8_000

            def getframerate(self):
                return 8_000

            def getnchannels(self):
                return 1

        with (
            patch("server.modules.export_service.take_audio_path", side_effect=lambda take: Path(str(take["id"]))),
            patch("server.modules.cue_mix.audio_file_identity", side_effect=lambda path: str(path)),
            patch("server.modules.overlap_mix.wave.open", side_effect=lambda *_args, **_kwargs: Header()),
        ):
            boundaries = prepare_overlap_boundaries(project)
            repeated = prepare_overlap_boundaries(json.loads(json.dumps(project)))

        self.assertEqual(header_reads, 244)
        self.assertEqual(len(boundaries), 243)
        self.assertEqual(repeated.keys(), boundaries.keys())

    def test_signed_starts_only_clamp_at_project_zero(self) -> None:
        starts, gaps = effective_unit_starts([3.0, 3.0, 2.0], [-1.0, -2.0])
        self.assertEqual(starts, [0.0, 2.0, 3.0])
        self.assertEqual(gaps, [-1.0, -2.0])
        short_starts, short_gaps = effective_unit_starts([0.5, 2.0], [-4.0])
        self.assertEqual(short_starts, [0.0, 0.0])
        self.assertEqual(short_gaps, [-0.5])
        following_short_starts, following_short_gaps = effective_unit_starts([2.0, 0.4], [-4.0])
        self.assertEqual(following_short_starts, [0.0, 0.0])
        self.assertAlmostEqual(following_short_gaps[0], -2.0)

    def test_reported_three_line_timing_fixture_keeps_both_half_second_overlaps(self) -> None:
        starts, gaps = effective_unit_starts([3.88, 2.36, 7.2], [-0.5, -0.5])

        self.assertEqual(starts, [0.0, 3.38, 5.24])
        self.assertEqual(gaps, [-0.5, -0.5])

    def test_following_is_preserved_and_true_peak_is_limited(self) -> None:
        previous = np.full((48_000, 1), 0.8, dtype=np.float32)
        following = np.full((48_000, 1), 0.7, dtype=np.float32)
        mixed, previous_gain, following_gain = reference_mix(previous, following, 48_000)
        self.assertAlmostEqual(previous_gain, 10 ** (-3 / 20), places=6)
        self.assertGreater(following_gain, 0)
        self.assertLessEqual(reference_true_peak(mixed), TRUE_PEAK_LIMIT + 1e-6)

    def test_natural_ducking_is_stable_across_phase_and_peak_fixtures(self) -> None:
        rate = 1_000
        positions = np.arange(rate, dtype=np.float32)
        tone = (np.sin(positions * 0.05) * 0.2)[:, None].astype(np.float32)
        pulse = np.zeros_like(tone)
        pulse[400, 0] = 0.8
        fixtures = [
            (tone, tone),
            (tone, -tone),
            (tone * 0.5, tone * 1.5),
            (tone, pulse),
        ]
        for previous, following in fixtures:
            with self.subTest(peak=float(np.max(np.abs(following)))):
                mixed, previous_gain, _following_gain = reference_mix(previous, following, rate)
                self.assertAlmostEqual(previous_gain, 10 ** (-3 / 20), places=6)
                self.assertLessEqual(reference_true_peak(mixed), TRUE_PEAK_LIMIT + 1e-6)
                before_exit = rate - round(rate * 0.01) - 1
                if np.max(np.abs(following)) < 0.5:
                    expected = following[before_exit] + previous[before_exit] * previous_gain
                    np.testing.assert_allclose(mixed[before_exit], expected, atol=1e-6)

    def test_leading_tail_uses_a_ten_millisecond_exit_ramp(self) -> None:
        previous = np.full((1_000, 1), 0.5, dtype=np.float32)
        following = np.zeros((1_000, 1), dtype=np.float32)
        mixed, previous_gain, _following_gain = reference_mix(previous, following, 1_000)
        self.assertAlmostEqual(float(mixed[-1, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(mixed[-10, 0]), 0.5 * previous_gain, places=6)

    def test_cached_overlap_is_pcm16(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, following, output = root / "a.wav", root / "b.wav", root / "mix.wav"
            for path, value in ((previous, 1000), (following, 2000)):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 1_000, 0, "NONE", "not compressed"))
                    writer.writeframes(np.full(1_000, value, dtype="<i2").tobytes())
            result = render_overlap(previous, following, 0.25, output)
            with wave.open(str(output), "rb") as reader:
                self.assertEqual((reader.getsampwidth(), reader.getnframes()), (2, 360))
            self.assertEqual(
                (result["durationSeconds"], result["preRollSeconds"], result["postRollSeconds"]),
                (0.25, 0.05, 0.06),
            )
            self.assertGreater(result["followingGain"], 0.99)

    def test_native_overlap_cancellation_discards_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, following, output = root / "a.wav", root / "b.wav", root / "mix.wav"
            for path in (previous, following):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 48_000, 0, "NONE", "not compressed"))
                    writer.writeframes(np.full(48_000, 1_000, dtype="<i2").tobytes())

            with self.assertRaises(InterruptedError):
                render_overlap(previous, following, 0.5, output, lambda: True)
            self.assertFalse(output.exists())

    def test_pre_roll_smoothly_reaches_the_safe_overlap_gain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, following, output = root / "a.wav", root / "b.wav", root / "mix.wav"
            for path, value in ((previous, 20_000), (following, 20_000)):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 1_000, 0, "NONE", "not compressed"))
                    writer.writeframes(np.full(1_000, value, dtype="<i2").tobytes())
            result = render_overlap(previous, following, 0.25, output)
            with wave.open(str(output), "rb") as reader:
                samples = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
            pre_roll_frames = round(result["preRollSeconds"] * 1_000)
            self.assertLessEqual(abs(int(samples[0]) - 20_000), 1)
            self.assertGreater(abs(int(samples[pre_roll_frames])), 20_000)
            self.assertLess(
                max(abs(int(samples[index + 1]) - int(samples[index])) for index in range(pre_roll_frames - 1)), 2_500
            )

    def test_native_overlap_matches_float32_reference_above_90_db_snr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous, following = root / "a.wav", root / "b.wav"
            positions = np.arange(2_000, dtype=np.float32)
            for path, samples in (
                (previous, np.sin(positions * 0.031) * 0.72),
                (following, np.sin(positions * 0.047 + 0.3) * 0.68),
            ):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 1_000, 0, "NONE", "not compressed"))
                    writer.writeframes(np.round(samples * 32768).astype("<i2").tobytes())
            actual, expected = root / "actual.wav", root / "expected.wav"
            result = render_overlap(previous, following, 1.0, actual)
            before, _ = _decode_pcm(previous)
            after, _ = _decode_pcm(following)
            rendered, previous_gain, _following_gain, _pre_roll, _post_roll = reference_render(
                before, after, 1_000, 1_000
            )
            reference_write(expected, rendered, 1_000)
            actual_samples, _ = _decode_pcm(actual)
            expected_samples, _ = _decode_pcm(expected)
            noise = actual_samples - expected_samples
            snr = 20 * np.log10(np.sqrt(np.mean(expected_samples**2)) / max(np.sqrt(np.mean(noise**2)), 1e-12))
            self.assertGreater(snr, 90)
            self.assertGreater(result["previousGain"], 0)

    def test_signature_covers_units_gap_and_algorithm(self) -> None:
        self.assertEqual(OVERLAP_ALGORITHM_VERSION, "adjacent-overlap-v6")
        base = overlap_signature({"take": "a", "duration": 3}, {"take": "b"}, -1)
        self.assertNotEqual(base, overlap_signature({"take": "c", "duration": 3}, {"take": "b"}, -1))
        self.assertNotEqual(base, overlap_signature({"take": "a", "duration": 3}, {"take": "b"}, -0.5))


if __name__ == "__main__":
    unittest.main()

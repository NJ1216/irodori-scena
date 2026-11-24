from __future__ import annotations

import math
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from server.modules.cue_mix import TRUE_PEAK_LIMIT, mix_pcm_members
from tools.pcm_analysis import decode_pcm as _decode_pcm, integrated_level as _integrated_level, true_peak as _true_peak
from server.modules.export_service import join_wav_files
from server.modules.overlap_mix import GAIN_RAMP_SECONDS, render_overlap


RATE = 48_000


def write_signal(path: Path, signal: np.ndarray, *, width: int = 2, channels: int = 1) -> None:
    values = np.repeat(signal[:, None], channels, axis=1).reshape(-1)
    scales = {1: 128, 2: 32768, 3: 8388608, 4: 2147483648}
    integers = np.round(np.clip(values, -1, 1 - 1 / scales[width]) * scales[width]).astype(np.int64)
    if width == 1:
        raw = (integers + 128).astype(np.uint8).tobytes()
    elif width == 2:
        raw = integers.astype("<i2").tobytes()
    elif width == 3:
        unsigned = integers & 0xFFFFFF
        raw = np.column_stack((unsigned, unsigned >> 8, unsigned >> 16)).astype(np.uint8).tobytes()
    else:
        raw = integers.astype("<i4").tobytes()
    with wave.open(str(path), "wb") as writer:
        writer.setparams((channels, width, RATE, 0, "NONE", "not compressed"))
        writer.writeframes(raw)


def tone(seconds: float, frequency: float, amplitude: float) -> np.ndarray:
    positions = np.arange(round(seconds * RATE), dtype=np.float64) / RATE
    return (np.sin(2 * math.pi * frequency * positions) * amplitude).astype(np.float32)


class AudioProcessingMatrixTests(unittest.TestCase):
    def test_pcm_decoder_supports_all_required_widths_and_stereo(self) -> None:
        reference = tone(0.02, 440, 0.7)
        tolerances = {1: 1 / 64, 2: 1 / 16384, 3: 1 / 4_000_000, 4: 1 / 1_000_000}
        for width in (1, 2, 3, 4):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "input.wav"
                write_signal(path, reference, width=width, channels=2)
                decoded, rate = _decode_pcm(path)
                self.assertEqual((rate, decoded.shape), (RATE, (len(reference), 2)))
                self.assertLess(float(np.max(np.abs(decoded[:, 0] - reference))), tolerances[width])
                np.testing.assert_array_equal(decoded[:, 0], decoded[:, 1])

    def test_two_to_eight_simultaneous_members_keep_offsets_duration_and_peak(self) -> None:
        for member_count in range(2, 9):
            with self.subTest(member_count=member_count), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                members: list[tuple[Path, float]] = []
                for index in range(member_count):
                    path = root / f"member-{index}.wav"
                    write_signal(path, tone(0.4 + index * 0.05, 220 + index * 110, 0.82))
                    members.append((path, index * 0.075))
                output = root / "cue.wav"
                duration = mix_pcm_members(members, output)
                mixed, rate = _decode_pcm(output)
                expected = max(offset + 0.4 + index * 0.05 for index, (_path, offset) in enumerate(members))
                self.assertLessEqual(abs(duration - expected), 1 / RATE)
                self.assertEqual(len(mixed), round(expected * RATE))
                self.assertLessEqual(_true_peak(mixed), TRUE_PEAK_LIMIT + 1 / 32768)
                self.assertTrue(np.any(mixed[:round(0.05 * rate)]))

    def test_native_two_to_eight_member_mix_matches_python_reference(self) -> None:
        from server.native_processing import mix_pcm_members_wav
        from tests.audio_cue_reference import mix_pcm_members as reference_mix

        for member_count in range(2, 9):
            with self.subTest(member_count=member_count), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                members = []
                for index in range(member_count):
                    path = root / f"member-{index}.wav"
                    write_signal(path, tone(0.6 + index * 0.02, 180 + index * 73, 0.32))
                    members.append((path, index * 0.013))
                python_output, rust_output = root / "python.wav", root / "rust.wav"
                python_duration = reference_mix(members, python_output)
                rust_duration = mix_pcm_members_wav(members, rust_output)
                python_samples, _ = _decode_pcm(python_output)
                rust_samples, _ = _decode_pcm(rust_output)
                self.assertEqual(rust_duration, python_duration)
                self.assertEqual(rust_samples.shape, python_samples.shape)
                noise = rust_samples - python_samples
                signal_rms = float(np.sqrt(np.mean(python_samples ** 2)))
                noise_rms = float(np.sqrt(np.mean(noise ** 2)))
                snr = 20 * math.log10(signal_rms / max(noise_rms, 1e-12))
                self.assertGreater(snr, 90)
                self.assertLessEqual(_true_peak(rust_samples), TRUE_PEAK_LIMIT + 1 / 32768)

    def test_simultaneous_mix_preserves_reference_loudness_within_point_one_db(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first, second, output = root / "a.wav", root / "b.wav", root / "mix.wav"
            write_signal(first, tone(1.0, 330, 0.18))
            write_signal(second, tone(0.7, 550, 0.18))
            mix_pcm_members([(first, 0), (second, 0.3)], output)
            mixed, _ = _decode_pcm(output)
            reference, _ = _decode_pcm(first)
            difference = 20 * math.log10((_integrated_level(mixed) or 1e-12) / (_integrated_level(reference) or 1e-12))
            self.assertLessEqual(abs(difference), 0.1)

    def test_silent_and_maximum_amplitude_cues_remain_bounded(self) -> None:
        for amplitude in (0.0, 32767 / 32768):
            with self.subTest(amplitude=amplitude), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                source, output = root / "source.wav", root / "mix.wav"
                write_signal(source, np.full(RATE // 10, amplitude, dtype=np.float32))
                mix_pcm_members([(source, 0), (source, 0)], output)
                mixed, _ = _decode_pcm(output)
                self.assertLessEqual(_true_peak(mixed), TRUE_PEAK_LIMIT + 1 / 32768)
                if amplitude == 0:
                    self.assertFalse(np.any(mixed))

    def test_overlap_of_a_simultaneous_cue_uses_ramp_and_preserves_duration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            voices = []
            for index, frequency in enumerate((220, 440, 660)):
                path = root / f"voice-{index}.wav"
                write_signal(path, tone(0.8, frequency, 0.45))
                voices.append((path, index * 0.05))
            cue, following, overlap = root / "cue.wav", root / "following.wav", root / "overlap.wav"
            mix_pcm_members(voices, cue)
            write_signal(following, tone(0.7, 880, 0.7))
            result = render_overlap(cue, following, 0.25, overlap)
            mixed, _ = _decode_pcm(overlap)
            self.assertEqual(len(mixed), round((0.25 + GAIN_RAMP_SECONDS + result["postRollSeconds"]) * RATE))
            self.assertLessEqual(_true_peak(mixed), TRUE_PEAK_LIMIT + 1 / 32768)
            self.assertEqual(result["preRollSeconds"], GAIN_RAMP_SECONDS)

    def test_consecutive_overlaps_do_not_duplicate_frames(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            sources = []
            for index, frequency in enumerate((220, 440, 660)):
                path = root / f"source-{index}.wav"
                write_signal(path, tone(1.0, frequency, 0.3))
                sources.append(path)
            output = root / "joined.wav"
            caches = [root / "overlap-0.wav", root / "overlap-1.wav"]
            render_overlap(sources[0], sources[1], 0.25, caches[0])
            render_overlap(sources[1], sources[2], 0.75, caches[1])
            join_wav_files(
                [(sources[0], -0.25), (sources[1], -0.75), (sources[2], 0)], output,
                overlap_files=[*caches, None],
            )
            with wave.open(str(output), "rb") as reader:
                self.assertEqual(reader.getnframes(), 2 * RATE)
                self.assertEqual(reader.getframerate(), RATE)

if __name__ == "__main__":
    unittest.main()

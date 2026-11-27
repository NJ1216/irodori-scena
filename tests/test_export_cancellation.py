from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from server.app import GenerationCancelled, render_overlap
from server.modules.export_service import (
    _individual_export,
    _prepare_export_lines,
    ensure_export_take,
    export_spoken_lines,
    join_wav_files,
    selected_take_is_available,
)


class ExportCancellationTests(unittest.TestCase):
    def test_individual_export_returns_ordered_wav_manifest_without_zip(self) -> None:
        with TemporaryDirectory() as directory:
            media_root = Path(directory) / "media"
            first = media_root / "takes" / "line-1.wav"
            second = media_root / "takes" / "line-2.wav"
            first.parent.mkdir(parents=True)
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            project = {
                "characters": [{"id": "cast-1", "name": "紗良"}],
                "scenes": [{"lines": [
                    {"id": "line-1", "text": "一行目", "characterId": "cast-1", "selectedTakeId": "take-1", "takes": [{"id": "take-1", "audioUrl": "/media/takes/line-1.wav"}]},
                    {"id": "line-2", "text": "二行目", "characterId": "cast-1", "selectedTakeId": "take-2", "takes": [{"id": "take-2", "audioUrl": "/media/takes/line-2.wav"}]},
                ]}],
            }
            with (
                patch("server.modules.constants.MEDIA_ROOT", media_root),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.export_service.update_export_job") as update_job,
            ):
                _individual_export("job-1", project, 0)
            result = update_job.call_args.kwargs
            self.assertEqual([item["fileName"] for item in result["files"]], ["0001_紗良.wav", "0002_紗良.wav"])
            self.assertTrue(all(item["audioUrl"].endswith(".wav") for item in result["files"]))
            self.assertTrue(all(Path(item["localPath"]).is_absolute() for item in result["files"]))
            self.assertNotIn("audioUrl", result)
            self.assertNotIn("fileName", result)
            self.assertEqual(list((media_root / "exports").glob("*.zip")), [])

    def test_prepared_export_does_not_reload_or_generate_per_line(self) -> None:
        with TemporaryDirectory() as directory:
            media_root = Path(directory) / "media"
            takes = []
            lines = []
            for index in range(100):
                audio = media_root / "takes" / f"line-{index}.wav"
                audio.parent.mkdir(parents=True, exist_ok=True)
                audio.write_bytes(b"RIFF existing take")
                take = {"id": f"take-{index}", "audioUrl": f"/media/takes/line-{index}.wav"}
                takes.append(take)
                lines.append({
                    "id": f"line-{index}", "text": "生成済み", "selectedTakeId": take["id"], "takes": [take],
                })
            project = {"scenes": [{"id": "scene", "lines": lines}]}
            with (
                patch("server.modules.constants.MEDIA_ROOT", media_root),
                patch("server.modules.project_repository.read_project") as read_project,
                patch("server.modules.script_routes.create_line_take") as create_take,
                patch("server.modules.export_service.update_export_job"),
            ):
                self.assertEqual(_prepare_export_lines("job-1", project, "fast"), 0)
            read_project.assert_not_called()
            create_take.assert_not_called()

    def test_joined_export_preserves_order_format_and_line_gap(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.wav"
            second = root / "second.wav"
            output = root / "joined.wav"
            for path, frames in ((first, b"\x01\x00" * 4), (second, b"\x02\x00" * 3)):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 10, 0, "NONE", "not compressed"))
                    writer.writeframes(frames)

            join_wav_files([(first, 0.2), (second, 0.0)], output)

            with wave.open(str(output), "rb") as reader:
                self.assertEqual((reader.getnchannels(), reader.getsampwidth(), reader.getframerate()), (1, 2, 10))
                self.assertEqual(reader.readframes(reader.getnframes()), b"\x01\x00" * 4 + b"\x00\x00" * 2 + b"\x02\x00" * 3)

    def test_joined_export_streams_signed_overlaps_without_duplicate_frames(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / f"{index}.wav" for index in range(3)]
            for index, path in enumerate(paths, 1):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 1_000, 0, "NONE", "not compressed"))
                    writer.writeframes((index.to_bytes(2, "little", signed=True)) * 1_000)
            output = root / "joined.wav"
            caches = [root / "overlap-0.wav", root / "overlap-1.wav"]
            render_overlap(paths[0], paths[1], 0.25, caches[0])
            render_overlap(paths[1], paths[2], 0.75, caches[1])
            join_wav_files(
                [(paths[0], -0.25), (paths[1], -0.75), (paths[2], 0)], output,
                overlap_files=[*caches, None],
            )
            with wave.open(str(output), "rb") as reader:
                self.assertEqual(reader.getnframes(), 2_000)

    def test_joined_export_needs_no_adjacent_overlap_cache(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "first.wav", root / "second.wav"]
            for path in paths:
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 1_000, 0, "NONE", "not compressed"))
                    writer.writeframes(b"\0\0" * 1_000)
            join_wav_files([(paths[0], -0.25), (paths[1], 0)], root / "joined.wav")
            with wave.open(str(root / "joined.wav"), "rb") as reader:
                self.assertEqual(reader.getnframes(), 1750)

    def test_joined_export_clamps_only_to_project_zero(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, cache, output = (
                root / name for name in ("first.wav", "second.wav", "cache.wav", "joined.wav")
            )
            for path, frames, value in ((first, 1_000, 1_000), (second, 400, 2_000)):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 1_000, 0, "NONE", "not compressed"))
                    writer.writeframes(np.full(frames, value, dtype="<i2").tobytes())
            render_overlap(first, second, 4, cache)
            join_wav_files([(first, -4), (second, 0)], output, overlap_files=[cache, None])
            with wave.open(str(output), "rb") as reader:
                self.assertEqual(reader.getnframes(), 1_000)

    def test_joined_export_ignores_v6_cache_and_matches_interval_render(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first, second, cache, output = (root / name for name in ("first.wav", "second.wav", "cache.wav", "joined.wav"))
            for path, value in ((first, 1_000), (second, 2_000)):
                with wave.open(str(path), "wb") as writer:
                    writer.setparams((1, 2, 1_000, 0, "NONE", "not compressed"))
                    writer.writeframes(np.full(1_000, value, dtype="<i2").tobytes())
            render_overlap(first, second, 0.25, cache)
            join_wav_files([(first, -0.25), (second, 0)], output, overlap_files=[cache, None])
            with wave.open(str(output), "rb") as reader:
                joined = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
            import scena_native
            reference = root / "reference.wav"
            scena_native.render_timeline_wav([(first, 0, 1000), (second, 750, 1000)], 0, 1750, 1000, 1, reference)
            with wave.open(str(reference), "rb") as reader:
                expected = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
            self.assertEqual(len(joined), 1_750)
            np.testing.assert_array_equal(joined, expected)

    def test_desktop_absolute_media_url_reuses_existing_selected_take(self) -> None:
        with TemporaryDirectory() as directory:
            media_root = Path(directory) / "media"
            audio = media_root / "takes" / "line-1" / "take-1.wav"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"RIFF existing take")
            line = {
                "selectedTakeId": "take-1",
                "takes": [{
                    "id": "take-1",
                    "audioUrl": "http://127.0.0.1:8787/media/takes/line-1/take-1.wav",
                }],
            }

            with patch("server.modules.constants.MEDIA_ROOT", media_root):
                self.assertTrue(selected_take_is_available(line))

    def test_export_spoken_lines_skips_only_explicitly_disabled_lines(self) -> None:
        project = {"scenes": [{"id": "scene", "lines": [
            {"id": "old", "text": "旧形式は有効"},
            {"id": "on", "text": "有効", "enabled": True},
            {"id": "off", "text": "無効", "enabled": False},
        ]}]}
        self.assertEqual(
            [line["id"] for _, line in export_spoken_lines(project)],
            ["old", "on"],
        )
    def test_cancellation_after_current_line_keeps_the_inference_worker_alive(self) -> None:
        project = {
            "settings": {"quality": "fast"},
            "scenes": [{"id": "scene-1", "lines": [{
                "id": "line-1", "text": "こんにちは", "characterId": "cast-1", "takes": [], "selectedTakeId": None,
            }]}],
        }
        cancel_checks = iter([False, True])
        with TemporaryDirectory() as directory:
            media_root = Path(directory) / "media"
            audio = media_root / "takes" / "line-1" / "take-1.wav"

            def create_take(*_args, **kwargs):
                self.assertIsNone(kwargs.get("should_cancel"))
                audio.parent.mkdir(parents=True)
                audio.write_bytes(b"RIFF completed synthesis")
                return {"id": "take-1", "audioUrl": "/media/takes/line-1/take-1.wav"}

            with (
                patch("server.modules.constants.MEDIA_ROOT", media_root),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.script_routes.create_line_take", side_effect=create_take),
                self.assertRaises(GenerationCancelled),
            ):
                ensure_export_take("line-1", "fast", should_cancel=lambda: next(cancel_checks))

            self.assertFalse(audio.exists())

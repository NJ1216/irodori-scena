from __future__ import annotations

import unittest
import tempfile
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import server.app  # noqa: F401 -- registers backend dependencies for the export boundary.
from server.modules.export_bundle import ExportLine, write_split
from server.modules.rhubarb_lipsync import (
    _lab_rows,
    _parse_cues,
    _remove_previous_cache_entries,
    _run_rhubarb,
    generate_rhubarb_lab,
    rhubarb_parallelism,
)


class RhubarbLipSyncTests(unittest.TestCase):
    def test_parallelism_distributes_logical_cpus_without_oversubscription(self) -> None:
        with patch("server.modules.rhubarb_lipsync.os.cpu_count", return_value=8):
            self.assertEqual(rhubarb_parallelism(1), (1, 8))
            self.assertEqual(rhubarb_parallelism(2), (2, 4))
            self.assertEqual(rhubarb_parallelism(10), (4, 2))

    def test_startup_cleanup_preserves_only_the_current_cache_session(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            current = root / "current-session"
            previous = root / "previous-session"
            current.mkdir()
            previous.mkdir()
            (current / "current.json").write_text("{}", encoding="utf-8")
            (previous / "old.json").write_text("{}", encoding="utf-8")
            (root / ".DS_Store").write_text("old", encoding="utf-8")

            _remove_previous_cache_entries(root, current)

            self.assertTrue((current / "current.json").is_file())
            self.assertFalse(previous.exists())
            self.assertFalse((root / ".DS_Store").exists())

    def test_maps_shapes_and_fills_the_entire_wav(self) -> None:
        cues = _parse_cues({"mouthCues": [{"start": 0.1, "end": 0.2, "value": "D"}, {"start": 0.2, "end": 0.3, "value": "X"}]})
        self.assertEqual(_lab_rows(cues, 0.5), [(0, 1_000_000, "pau"), (1_000_000, 2_000_000, "a"), (2_000_000, 5_000_000, "pau")])

    def test_rejects_unknown_and_overlapping_cues(self) -> None:
        with self.assertRaises(ValueError):
            _parse_cues({"mouthCues": [{"start": 0, "end": 1, "value": "G"}]})
        with self.assertRaises(ValueError):
            _parse_cues({"mouthCues": [{"start": 0.5, "end": 1, "value": "D"}, {"start": 0.2, "end": 0.7, "value": "E"}]})

    def test_split_export_keeps_wav_when_one_lab_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wav_path = root / "source.wav"
            (root / "out").mkdir()
            with wave.open(str(wav_path), "wb") as writer:
                writer.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
                writer.writeframes(b"\0\0" * 160)
            line = {"id": "line", "text": "本文"}
            item = ExportLine(1, {}, line, "キャスト", "本文", "001")
            with patch("server.modules.export_bundle.selected_audio", return_value=wav_path), patch(
                "server.modules.rhubarb_lipsync.generate_rhubarb_lab", side_effect=RuntimeError("解析失敗")
            ):
                count, failures = write_split(root / "out", {}, [item], ["wav", "lab"], "\t", False, False, "job")
            self.assertEqual(count, 1)
            self.assertTrue((root / "out" / "001.wav").is_file())
            self.assertFalse((root / "out" / "001.lab").exists())
            self.assertEqual(failures, [{"lineId": "line", "lineNumber": 1, "reason": "解析失敗"}])

    def test_split_export_generates_multiple_labs_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wav_paths = [root / "one.wav", root / "two.wav"]
            (root / "out").mkdir()
            for wav_path in wav_paths:
                with wave.open(str(wav_path), "wb") as writer:
                    writer.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
                    writer.writeframes(b"\0\0" * 160)
            items = [
                ExportLine(index, {}, {"id": f"line-{index}", "text": "本文"}, "キャスト", "本文", f"{index:03d}")
                for index in (1, 2)
            ]
            rendezvous = threading.Barrier(2)
            received_threads: list[int] = []

            def generate(_path: Path, _cancel: object, thread_count: int) -> str:
                received_threads.append(thread_count)
                rendezvous.wait(timeout=2)
                return "0 100 pau\n"

            # Pin the plain Rhubarb path: an installed Japanese add-on on the test machine must not be used.
            with patch("server.modules.japanese_lipsync_session.export_addon_session", lambda: nullcontext(None)), patch(
                "server.modules.export_bundle.selected_audio", side_effect=wav_paths
            ), patch(
                "server.modules.rhubarb_lipsync.rhubarb_parallelism", return_value=(2, 3)
            ), patch("server.modules.rhubarb_lipsync.generate_rhubarb_lab", side_effect=generate), patch(
                "server.modules.export_service.update_export_job"
            ) as update_job:
                count, failures = write_split(root / "out", {}, items, ["lab"], "\t", False, False, "job")

            self.assertEqual((count, failures), (2, []))
            self.assertEqual(received_threads, [3, 3])
            self.assertTrue((root / "out" / "001.lab").is_file())
            self.assertTrue((root / "out" / "002.lab").is_file())
            self.assertEqual(update_job.call_count, 2)
            self.assertEqual(update_job.call_args.kwargs["alignmentCompletedLines"], 2)

    def test_running_rhubarb_is_terminated_when_export_is_cancelled(self) -> None:
        process = Mock()
        process.poll.return_value = None
        process.communicate.return_value = ("", "")
        with patch("server.modules.rhubarb_lipsync.subprocess.Popen", return_value=process), self.assertRaises(
            server.app.GenerationCancelled
        ):
            _run_rhubarb(["rhubarb"], Path("."), 30, lambda: True)
        process.terminate.assert_called_once_with()

    def test_identical_concurrent_wavs_share_one_rhubarb_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wav_path = root / "same.wav"
            with wave.open(str(wav_path), "wb") as writer:
                writer.setparams((1, 2, 16_000, 0, "NONE", "not compressed"))
                writer.writeframes(b"\0\0" * 160)
            entered = threading.Event()
            release = threading.Event()
            calls = 0

            def run(command: list[str], _cwd: Path, _timeout: float, _cancel: object) -> None:
                nonlocal calls
                calls += 1
                entered.set()
                release.wait(timeout=2)
                output = Path(command[command.index("-o") + 1])
                output.write_text('{"mouthCues":[{"start":0,"end":0.01,"value":"X"}]}')

            with patch("server.modules.constants.RHUBARB_CACHE_ROOT", root / "cache"), patch(
                "server.modules.rhubarb_runtime.rhubarb_executable", return_value=root / "rhubarb"
            ), patch("server.modules.rhubarb_runtime.rhubarb_status", return_value={"releaseId": "test"}), patch(
                "server.modules.rhubarb_lipsync._run_rhubarb", side_effect=run
            ), ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(generate_rhubarb_lab, wav_path, lambda: False, 2)
                self.assertTrue(entered.wait(timeout=2))
                second = executor.submit(generate_rhubarb_lab, wav_path, lambda: False, 2)
                release.set()
                self.assertEqual(first.result(timeout=2), second.result(timeout=2))

            self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()

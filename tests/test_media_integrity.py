from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.app import app as _registered_app  # noqa: F401
from server.modules import constants, project_routes
from server.modules.cue_mix import cue_mix_signature, render_cue_mix
from server.modules.media_integrity import reconcile_project_media
from server.modules.overlap_mix import overlap_cache_signatures, render_adjacent_overlap


def write_wav(path: Path, frames: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8_000)
        audio.writeframes(b"\0\0" * frames)


class MediaIntegrityTests(unittest.TestCase):
    def test_explicit_workspace_save_persists_completed_derived_audio(self) -> None:
        project = {"id": "project", "characters": [], "scenes": []}
        with (
            patch.object(constants, "ACTIVE_PROJECT_PATH", Path("saved.scena")),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.project_repository.materialize_cast_global_characters", return_value=project),
            patch("server.modules.project_repository.write_project", return_value=project),
            patch("server.modules.project_container.persist_active_container") as persist,
            patch("server.modules.workspace.workspace_info", return_value={"name": "saved.scena"}),
        ):
            project_routes.save_workspace()

        persist.assert_called_once_with()

    def test_derived_mix_generation_skips_container_sync_and_shares_same_signature(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            paths = [media / "takes" / f"line-{index}" / f"take-{index}.wav" for index in range(2)]
            for path in paths:
                write_wav(path, 800)
            lines = [
                self._line("line-0", "take-0", paths[0], cue_id="cue"),
                self._line("line-1", "take-1", paths[1], cue_id="cue", offset=0.02),
            ]
            scene = {"id": "scene", "lines": lines}
            calls = 0

            def render(_members, output):
                nonlocal calls
                calls += 1
                write_wav(output, 960)
                return 0.12

            with (
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.cue_mix.mix_pcm_members", side_effect=render),
                patch("server.modules.project_container.persist_active_container") as persist,
            ):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _index: render_cue_mix(scene, "line-0"), range(2)))

            self.assertEqual(calls, 1)
            self.assertEqual(results[0]["signature"], results[1]["signature"])
            persist.assert_not_called()

    def test_missing_selected_take_does_not_abort_cache_reconciliation(self) -> None:
        project = {
            "settings": {"lineGap": 0.7},
            "scenes": [
                {
                    "lines": [
                        {
                            "id": "line-1",
                            "selectedTakeId": "take-1",
                            "takes": [{"id": "take-1", "file": "/missing/take.wav"}],
                        }
                    ]
                }
            ],
        }

        with patch(
            "server.modules.export_service.take_audio_path", side_effect=RuntimeError("Selected take WAV is missing.")
        ):
            self.assertEqual(overlap_cache_signatures(project), set())

    def test_app_startup_reconciles_the_restored_project_media(self) -> None:
        project = {"characters": [], "scenes": []}
        with (
            patch("server.modules.workspace.ensure_data_root"),
            patch("server.modules.tts_registry.ensure_tts_storage"),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.media_integrity.reconcile_project_media", return_value=0) as reconcile,
            patch("server.modules.project_cache_cleanup.cleanup_loaded_project") as cleanup,
            patch("server.modules.pronunciation_dictionary.pronunciation_characters", return_value=[]) as characters,
            patch("server.modules.pronunciation_dictionary.reconcile_cast_pronunciations") as pronunciations,
            patch.object(project_routes, "_prepare_tts_when_eager"),
        ):
            project_routes.startup()

        reconcile.assert_called_once_with(project)
        cleanup.assert_called_once_with(project)
        characters.assert_called_once_with(project)
        pronunciations.assert_called_once_with([])

    def test_app_startup_persists_pronunciation_backfill_as_project_only(self) -> None:
        project = {"characters": [], "scenes": [], "pronunciationDictionary": []}
        with (
            patch("server.modules.workspace.ensure_data_root"),
            patch("server.modules.tts_registry.ensure_tts_storage"),
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.pronunciation_dictionary.pronunciation_characters", return_value=[]),
            patch("server.modules.pronunciation_dictionary.reconcile_cast_pronunciations"),
            patch("server.modules.project_pronunciation_snapshot.reconcile_script_pronunciations", return_value=True),
            patch("server.modules.media_integrity.reconcile_project_media", return_value=0),
            patch("server.modules.project_repository.write_project") as write_project,
            patch.object(project_routes, "_prepare_tts_when_eager"),
        ):
            project_routes.startup()

        write_project.assert_called_once_with(project, project_only=True)

    def test_project_open_adds_pronunciations_without_history_and_syncs_only_project_json(self) -> None:
        project = {"id": "project", "characters": [], "scenes": [], "pronunciationDictionary": [], "revision": 4}
        saved = {**project, "revision": 5, "pronunciationDictionary": [{"id": "auto"}]}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "opened.scena"
            selected.write_bytes(b"container")

            def extract(_selected, target):
                target.mkdir(parents=True)
                (target / "project.json").write_text("{}", encoding="utf-8")

            with (
                patch.object(project_routes, "_selected_project_file", return_value=selected),
                patch("server.modules.project_container.container_signature", return_value={}),
                patch("server.modules.project_container.container_requires_upgrade", return_value=False),
                patch("server.modules.project_container.working_root", return_value=root / "workspace"),
                patch("server.modules.project_container.extract_container", side_effect=extract),
                patch("server.modules.project_models.StudioProjectModel.model_validate"),
                patch("server.modules.inference.shutdown_inference_worker"),
                patch("server.modules.workspace.activate_project_container"),
                patch("server.modules.workspace.ensure_data_root"),
                patch("server.modules.history.begin_history_session") as begin_history,
                patch("server.modules.project_repository.read_project", return_value=project),
                patch(
                    "server.modules.project_pronunciation_snapshot.reconcile_script_pronunciations", return_value=True
                ),
                patch("server.modules.media_integrity.reconcile_project_media", return_value=0),
                patch("server.modules.project_cache_cleanup.cleanup_loaded_project") as cleanup,
                patch("server.modules.project_repository.write_project", return_value=saved) as write_project,
                patch("server.modules.cast_sync.global_cast_update_candidates", return_value=[]),
                patch("server.modules.script_assistant_summary.clear_script_assistant_summary_cache"),
                patch("server.modules.derived_audio_preparation.reset_overlap_preparation") as reset_preparation,
                patch.object(project_routes, "_prepare_tts_when_eager"),
            ):
                result = project_routes.open_workspace()

        begin_history.assert_called_once_with()
        write_project.assert_called_once_with(project, project_only=True)
        reset_preparation.assert_called_once_with()
        cleanup.assert_called_once_with(saved)
        self.assertEqual(result["project"], saved)

    def test_keeps_current_mix_signatures_and_removes_stale_cache_files(self) -> None:
        with TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            paths = [media / "takes" / f"line-{index}" / f"take-{index}.wav" for index in range(3)]
            for index, path in enumerate(paths):
                write_wav(path, 8_000 + index * 400)
            lines = [
                self._line("line-0", "take-0", paths[0], cue_id="cue", gap=-0.2),
                self._line("line-1", "take-1", paths[1], cue_id="cue", offset=0.1),
                self._line("line-2", "take-2", paths[2]),
            ]
            project = {"settings": {"lineGap": 0.7}, "scenes": [{"id": "scene", "lines": lines}]}
            with patch.object(constants, "MEDIA_ROOT", media):
                cue_signature = cue_mix_signature(lines[:2])
                cue_root = media / "cache" / "cue-mixes"
                overlap_root = media / "cache" / "overlap-mixes"
                write_wav(cue_root / f"{cue_signature}.wav", 9_200)
                with (
                    patch(
                        "server.modules.overlap_mix.render_overlap",
                        return_value={
                            "durationSeconds": 0.2,
                            "preRollSeconds": 0.05,
                            "postRollSeconds": 0.01,
                            "followingGain": 1.0,
                        },
                    ),
                ):
                    rendered = render_adjacent_overlap(project, "line-0")
                overlap_signature = str(rendered["signature"])
                self.assertEqual(overlap_cache_signatures(project), {overlap_signature})
                write_wav(overlap_root / f"{overlap_signature}.wav", 1_600)
                (cue_root / "stale.wav").write_bytes(b"cache")
                (overlap_root / "stale.wav").write_bytes(b"cache")

                repaired = reconcile_project_media(project)

            self.assertEqual(repaired, 0)
            self.assertTrue((cue_root / f"{cue_signature}.wav").is_file())
            self.assertTrue((overlap_root / f"{overlap_signature}.wav").is_file())
            self.assertFalse((cue_root / "stale.wav").exists())
            self.assertFalse((overlap_root / "stale.wav").exists())

    @staticmethod
    def _line(
        line_id: str,
        take_id: str,
        path: Path,
        *,
        cue_id: str | None = None,
        gap: float | None = None,
        offset: float | None = None,
    ) -> dict[str, object]:
        line: dict[str, object] = {
            "id": line_id,
            "characterId": line_id,
            "text": line_id,
            "takes": [{"id": take_id, "audioUrl": f"/media/{path.relative_to(path.parents[2]).as_posix()}"}],
            "selectedTakeId": take_id,
        }
        if cue_id is not None:
            line["cueId"] = cue_id
        if gap is not None:
            line["gapSeconds"] = gap
        if offset is not None:
            line["startOffsetSeconds"] = offset
        return line


if __name__ == "__main__":
    unittest.main()

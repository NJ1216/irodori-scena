from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import os
import sqlite3
import tempfile
import unittest
import wave
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from server.app import create_app
from server.modules import constants, project_cache_cleanup, project_cache_storage, project_container
from server.modules.timeline import project_timeline
from server.modules.timeline_intervals import describe_interval
from server.modules.cue_mix import cue_mix_signature
from server.modules.overlap_mix import overlap_cache_signatures


def _wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\0\0" * 2400)


def _names(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as connection:
        return {row[0] for row in connection.execute("SELECT path FROM entries")}


class ProjectCacheCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        create_app()

    def test_clean_loaded_project_skips_sqlite_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, saved = base / "work", base / "test.scena"
            root.mkdir()
            project = {"scenes": [{"lines": []}], "characters": []}
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            project_container.sync_container(saved, root)
            before = saved.read_bytes()
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(project_cache_storage.uuid, "uuid4", side_effect=AssertionError("rebuild started")),
            ):
                self.assertFalse(project_cache_cleanup.project_optimization_available(project))
                project_cache_cleanup.cleanup_loaded_project(project)
            self.assertEqual(saved.read_bytes(), before)

    def test_empty_script_discards_caches_and_reclaims_file_space(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, saved = base / "work", base / "test.scena"
            root.mkdir()
            project = {"scenes": [{"lines": []}], "characters": []}
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            for kind in ("cue-mixes", "overlap-mixes", "timeline-v1"):
                _wav(root / "media" / "cache" / kind / "stale.wav")
            (root / "unused.bin").write_bytes(os.urandom(1024 * 1024))
            project_container.sync_container(saved, root)
            old_staging = saved.with_name(f".{saved.name}.staging-9996")
            old_journal = saved.with_name(f"{old_staging.name}-journal")
            old_staging.write_bytes(b"interrupted")
            old_journal.write_bytes(b"journal")
            before = saved.stat().st_size
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
            ):
                project_cache_cleanup.cleanup_loaded_project(project)
            self.assertLess(saved.stat().st_size, before)
            self.assertEqual(_names(saved), {"project.json"})
            self.assertFalse((root / "unused.bin").exists())
            self.assertFalse(old_staging.exists())
            self.assertFalse(old_journal.exists())

    def test_all_line_takes_and_cast_media_survive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, saved = base / "work", base / "test.scena"
            root.mkdir()
            first = root / "media/takes/line/first.wav"
            second = root / "media/takes/line/second.wav"
            cast = root / "media/characters/cast/reference.wav"
            for path in (first, second, cast, root / "media/takes/orphan.wav"):
                _wav(path)
            project = {
                "characters": [{"referenceAudioUrl": "/media/characters/cast/reference.wav"}],
                "scenes": [{"lines": [{"takes": [
                    {"id": "a", "audioUrl": "/media/takes/line/first.wav"},
                    {"id": "b", "audioUrl": "/media/takes/line/second.wav"},
                ], "selectedTakeId": "a"}]}],
            }
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            project_container.sync_container(saved, root)
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
            ):
                project_cache_cleanup.cleanup_loaded_project(project)
            names = _names(saved)
            self.assertIn("media/takes/line/first.wav", names)
            self.assertIn("media/takes/line/second.wav", names)
            self.assertIn("media/characters/cast/reference.wav", names)
            self.assertNotIn("media/takes/orphan.wav", names)

    def test_failed_rebuild_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, saved = base / "work", base / "test.scena"
            root.mkdir()
            (root / "project.json").write_text("{}", encoding="utf-8")
            (root / "unused.bin").write_bytes(b"unused")
            project_container.sync_container(saved, root)
            original = saved.read_bytes()
            with patch.object(project_container, "validate_container", side_effect=ValueError("invalid")):
                with self.assertRaisesRegex(ValueError, "invalid"):
                    project_cache_storage.compact_container_entries(saved, {"project.json"})
            self.assertEqual(saved.read_bytes(), original)

    def test_timeline_caches_are_never_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, saved = base / "work", base / "test.scena"
            root.mkdir()
            _wav(root / "media/takes/line/take.wav")
            project = {
                "id": "project-1", "revision": 1, "characters": [],
                "settings": {"lineGap": 0.7},
                "scenes": [{"lines": [{
                    "id": "line-1", "text": "line", "characterId": "cast-1", "enabled": True,
                    "selectedTakeId": "take-1", "takes": [{
                        "id": "take-1", "audioUrl": "/media/takes/line/take.wav",
                    }],
                }]}],
            }
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            legacy = root / "media/cache/timeline-v1/legacy.wav"
            _wav(legacy)
            project_container.sync_container(saved, root)
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
            ):
                plan = project_timeline(project)
                interval = describe_interval(plan, 0, 2400)
                valid = Path(interval["output"])
                _wav(valid)
                project_cache_storage.persist_derived_cache(valid, interval)
                with project_container._connect(saved, readonly=True) as connection:
                    stored = connection.execute(
                        "SELECT compression FROM entries WHERE path=?", (valid.relative_to(root).as_posix(),)
                    ).fetchone()
                self.assertIsNone(stored)
                project_cache_cleanup.cleanup_loaded_project(project)
                first_size = saved.stat().st_size
                self.assertFalse(project_cache_storage.compact_container_entries(saved, _names(saved)))
            names = _names(saved)
            self.assertNotIn(valid.relative_to(root).as_posix(), names)
            self.assertNotIn(legacy.relative_to(root).as_posix(), names)
            self.assertEqual(saved.stat().st_size, first_size)

    def test_current_cue_and_overlap_caches_survive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, saved = base / "work", base / "test.scena"
            root.mkdir()
            lines = []
            for index in range(3):
                _wav(root / f"media/takes/line-{index}/take.wav")
                lines.append({
                    "id": f"line-{index}", "text": "line", "characterId": "cast-1",
                    "cueId": "cue-1" if index < 2 else None,
                    "gapSeconds": -0.05 if index == 0 else None,
                    "selectedTakeId": f"take-{index}", "takes": [{
                        "id": f"take-{index}", "audioUrl": f"/media/takes/line-{index}/take.wav",
                    }],
                })
            project = {"settings": {"lineGap": 0.7}, "characters": [], "scenes": [{"lines": lines}]}
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            with patch.object(constants, "MEDIA_ROOT", root / "media"):
                cue = cue_mix_signature(lines[:2])
                overlaps = overlap_cache_signatures(project)
            self.assertTrue(overlaps)
            cue_file = root / f"media/cache/cue-mixes/{cue}.wav"
            overlap_files = [root / f"media/cache/overlap-mixes/{key}.wav" for key in overlaps]
            for path in (cue_file, *overlap_files,
                         root / "media/cache/cue-mixes/stale.wav",
                         root / "media/cache/overlap-mixes/stale.wav"):
                _wav(path)
            project_container.sync_container(saved, root)
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
            ):
                project_cache_cleanup.cleanup_loaded_project(project)
            names = _names(saved)
            self.assertIn(cue_file.relative_to(root).as_posix(), names)
            for path in overlap_files:
                self.assertIn(path.relative_to(root).as_posix(), names)
            self.assertNotIn("media/cache/cue-mixes/stale.wav", names)
            self.assertNotIn("media/cache/overlap-mixes/stale.wav", names)

    def test_scratch_timeline_cache_is_excluded_from_first_save(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            root, saved = base / "work", base / "test.scena"
            root.mkdir()
            _wav(root / "media/takes/line/take.wav")
            project = {
                "id": "project-1", "characters": [], "settings": {"lineGap": 0.7},
                "scenes": [{"lines": [{
                    "id": "line-1", "text": "line", "characterId": "cast-1",
                    "selectedTakeId": "take-1", "takes": [{
                        "id": "take-1", "audioUrl": "/media/takes/line/take.wav",
                    }],
                }]}],
            }
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
            ):
                interval = describe_interval(project_timeline(project), 0, 2400)
                valid = Path(interval["output"])
                _wav(valid)
                project_cache_storage.persist_derived_cache(valid, interval)
            project_container.sync_container(saved, root)
            with (
                patch.object(constants, "ACTIVE_PROJECT_PATH", saved),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
            ):
                project_cache_cleanup.cleanup_loaded_project(project)
            names = _names(saved)
            self.assertNotIn(valid.relative_to(root).as_posix(), names)
            self.assertNotIn("media/cache/timeline-v1/.provenance.json", names)


if __name__ == "__main__":
    unittest.main()

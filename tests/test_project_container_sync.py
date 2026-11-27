from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app as _registered_app  # noqa: F401
from server.modules import constants, project_container
from server.modules.media_integrity import reconcile_project_media


class ProjectContainerTests(unittest.TestCase):
    def _tree(self, root: Path) -> None:
        (root / "media/takes/line").mkdir(parents=True)
        (root / "media/cache/waves").mkdir(parents=True)
        (root / "empty").mkdir()
        (root / "project.json").write_bytes(b'{"version":1,"title":"test"}')
        (root / "media/takes/line/take.wav").write_bytes((b"RIFFaudio" * 20000))
        (root / "media/cache/waves/cache.bin").write_bytes(b"cache" * 100)
        (root / "image.png").write_bytes(b"\x89PNG\r\n" + bytes(range(256)))
        (root / "unknown.bin").write_bytes(b"\x00\xffunknown")
        (root / "media/exports/result.wav").parent.mkdir(parents=True)
        (root / "media/exports/result.wav").write_bytes(b"excluded")

    def test_round_trip_preserves_files_and_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, extracted, container = base / "source", base / "out", base / "test.scena"
            source.mkdir()
            self._tree(source)
            project_container.sync_container(container, source)
            project_container.extract_container(container, extracted)

            for relative in (
                "project.json",
                "media/takes/line/take.wav",
                "media/cache/waves/cache.bin",
                "image.png",
                "unknown.bin",
            ):
                self.assertEqual((source / relative).read_bytes(), (extracted / relative).read_bytes())
            self.assertTrue((extracted / "empty").is_dir())
            self.assertFalse((extracted / "media/exports").exists())
            connection = sqlite3.connect(container)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA application_id").fetchone()[0], project_container.APPLICATION_ID
                )
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                methods = dict(connection.execute("SELECT path, compression FROM entries"))
            finally:
                connection.close()
            self.assertEqual(methods["image.png"], "none")
            self.assertEqual(methods["media/takes/line/take.wav"], "zstd")

    def test_incremental_update_reuses_unchanged_blob_and_removes_deleted_entry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            self._tree(source)
            project_container.sync_container(container, source)
            connection = sqlite3.connect(container)
            try:
                before = connection.execute("SELECT rowid FROM entries WHERE path='unknown.bin'").fetchone()[0]
            finally:
                connection.close()
            (source / "project.json").write_bytes(b'{"version":1,"title":"changed"}')
            (source / "image.png").unlink()
            project_container.sync_container(container, source)
            connection = sqlite3.connect(container)
            try:
                after = connection.execute("SELECT rowid FROM entries WHERE path='unknown.bin'").fetchone()[0]
                names = {row[0] for row in connection.execute("SELECT path FROM entries")}
            finally:
                connection.close()
            self.assertEqual(before, after)
            self.assertNotIn("image.png", names)

    def test_compact_sync_rebuilds_the_container_without_deleted_blob_pages(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            (source / "project.json").write_text("{}", encoding="utf-8")
            disposable = source / "media/takes/line/take.png"
            disposable.parent.mkdir(parents=True)
            disposable.write_bytes(os.urandom(2 * 1024 * 1024))
            project_container.sync_container(container, source)
            before = container.stat().st_size

            disposable.unlink()
            project_container.sync_container(container, source, compact=True)

            self.assertLess(container.stat().st_size, before // 2)
            with closing(sqlite3.connect(container)) as connection:
                names = {row[0] for row in connection.execute("SELECT path FROM entries")}
            self.assertNotIn("media/takes/line/take.png", names)

    def test_failed_compact_validation_preserves_original_container(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            (source / "project.json").write_text("{}", encoding="utf-8")
            project_container.sync_container(container, source)
            original = container.read_bytes()
            (source / "project.json").write_text('{"changed":true}', encoding="utf-8")
            with patch.object(project_container, "validate_container", side_effect=ValueError("invalid")):
                with self.assertRaisesRegex(ValueError, "invalid"):
                    project_container.sync_container(container, source, compact=True)
            self.assertEqual(container.read_bytes(), original)

    def test_empty_script_prunes_mix_caches_and_compacts_container(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            project = {"scenes": [{"lines": []}]}
            (source / "project.json").write_text(json.dumps(project), encoding="utf-8")
            for kind in ("cue-mixes", "overlap-mixes"):
                cache = source / "media" / "cache" / kind / "stale.wav"
                cache.parent.mkdir(parents=True)
                cache.write_bytes(os.urandom(1024 * 1024))
            (source / "other.bin").write_bytes(b"keep")
            project_container.sync_container(container, source)
            before = container.stat().st_size

            with patch.object(constants, "MEDIA_ROOT", source / "media"):
                reconcile_project_media(project)
            project_container.sync_container(container, source, compact=True)

            self.assertLess(container.stat().st_size, before // 2)
            with closing(sqlite3.connect(container)) as connection:
                names = {row[0] for row in connection.execute("SELECT path FROM entries")}
            self.assertIn("other.bin", names)
            self.assertNotIn("media/cache/cue-mixes/stale.wav", names)
            self.assertNotIn("media/cache/overlap-mixes/stale.wav", names)

    def test_ordinary_sync_preserves_overlap_cache_without_importing_new_derived_audio(self) -> None:
        for cache_kind in ("overlap-mixes",):
            with tempfile.TemporaryDirectory() as raw:
                base = Path(raw)
                source, container = base / "source", base / "test.scena"
                source.mkdir()
                (source / "project.json").write_text("{}", encoding="utf-8")
                overlap_root = source / f"media/cache/{cache_kind}"
                overlap_root.mkdir(parents=True)
                old_mix = overlap_root / "old.wav"
                old_mix.write_bytes(b"old")
                project_container.sync_container(container, source)

                old_mix.unlink()
                (overlap_root / "new.wav").write_bytes(b"new")
                project_container.sync_container(container, source, include_derived_audio=False)
                with closing(sqlite3.connect(container)) as connection:
                    ordinary_names = {row[0] for row in connection.execute("SELECT path FROM entries")}
                self.assertIn(f"media/cache/{cache_kind}/old.wav", ordinary_names)
                self.assertNotIn(f"media/cache/{cache_kind}/new.wav", ordinary_names)

                project_container.sync_container(container, source)
                with closing(sqlite3.connect(container)) as connection:
                    explicit_names = {row[0] for row in connection.execute("SELECT path FROM entries")}
                self.assertNotIn(f"media/cache/{cache_kind}/old.wav", explicit_names)
                self.assertIn(f"media/cache/{cache_kind}/new.wav", explicit_names)

    def test_incremental_index_avoids_reading_unchanged_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            self._tree(source)
            project_container.sync_container(container, source)

            with patch.object(
                project_container, "_compressed_copy", wraps=project_container._compressed_copy
            ) as compress:
                project_container.sync_container(container, source)
            compress.assert_not_called()

            changed = source / "unknown.bin"
            changed.write_bytes(b"changed!!")
            with patch.object(
                project_container, "_compressed_copy", wraps=project_container._compressed_copy
            ) as compress:
                project_container.sync_container(container, source)
            self.assertEqual([call.args[0] for call in compress.call_args_list], [changed])

    def test_corrupt_incremental_index_falls_back_to_full_sync_and_is_not_stored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            self._tree(source)
            project_container.sync_container(container, source)
            index = source / project_container.SYNC_INDEX_NAME
            index.write_text("not-json", encoding="utf-8")

            with patch.object(
                project_container, "_compressed_copy", wraps=project_container._compressed_copy
            ) as compress:
                project_container.sync_container(container, source)
            self.assertGreater(compress.call_count, 1)
            with closing(sqlite3.connect(container)) as connection:
                names = {row[0] for row in connection.execute("SELECT path FROM entries")}
            self.assertNotIn(project_container.SYNC_INDEX_NAME, names)

    def test_project_only_sync_skips_tree_walk_with_valid_index(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            self._tree(source)
            project_container.sync_container(container, source)
            (source / "project.json").write_text('{"title":"changed"}', encoding="utf-8")
            with patch.object(project_container, "_iter_paths", wraps=project_container._iter_paths) as walk:
                fast = project_container.sync_project_entry(container, source)
            self.assertTrue(fast)
            walk.assert_not_called()

    def test_project_only_sync_falls_back_when_index_is_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            self._tree(source)
            project_container.sync_container(container, source)
            (source / project_container.SYNC_INDEX_NAME).write_text("broken", encoding="utf-8")
            with patch.object(project_container, "_iter_paths", wraps=project_container._iter_paths) as walk:
                fast = project_container.sync_project_entry(container, source)
            self.assertFalse(fast)
            self.assertTrue(walk.called)

    def test_rejects_traversal_hash_mismatch_version_and_invalid_deflate(self) -> None:
        for mutation in ("path", "hash", "version", "deflate", "size"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                base = Path(raw)
                source, output, container = base / "source", base / "out", base / "test.scena"
                source.mkdir()
                (source / "project.json").write_text("{}")
                project_container.sync_container(container, source)
                connection = sqlite3.connect(container)
                try:
                    if mutation == "path":
                        connection.execute("UPDATE entries SET path='../project.json'")
                    elif mutation == "hash":
                        connection.execute("UPDATE entries SET sha256=?", ("0" * 64,))
                    elif mutation == "version":
                        connection.execute("PRAGMA user_version=3")
                    elif mutation == "size":
                        connection.execute(
                            "UPDATE entries SET original_size=?", (project_container.MAX_ENTRY_SIZE + 1,)
                        )
                    else:
                        connection.execute("UPDATE entries SET compression='deflate', data=X'00'")
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaises(HTTPException):
                    project_container.extract_container(container, output)




if __name__ == "__main__":
    unittest.main()

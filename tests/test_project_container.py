from __future__ import annotations

import scena_test_isolation  # noqa: F401
import hashlib
import tempfile
import unittest
import zlib
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app as _registered_app  # noqa: F401
from server.modules import project_container


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

    def test_partial_save_writes_zstd_and_restores_take(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "saved.scena"
            (source / "media/takes/line").mkdir(parents=True)
            (source / "project.json").write_bytes(b"{}")
            project_container.sync_container(container, source)
            payload = b"RIFF" + b"audio" * 1000
            (source / "media/takes/line/new.wav").write_bytes(payload)
            project_container.sync_project_and_media_targets(container, source, ["takes/line"])
            with closing(project_container._connect(container, readonly=True)) as connection:
                method = connection.execute("SELECT compression FROM entries WHERE path=?", ("media/takes/line/new.wav",)).fetchone()[0]
            self.assertEqual(method, "zstd")
            project_container.extract_container(container, base / "opened")
            self.assertEqual((base / "opened/media/takes/line/new.wav").read_bytes(), payload)

    def test_v1_save_upgrades_atomically_and_preserves_unchanged_deflate(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "saved.scena"
            source.mkdir()
            payload = b"old take" * 1000
            (source / "project.json").write_bytes(b'{"title":"old"}')
            (source / "take.wav").write_bytes(payload)
            with closing(project_container._connect(container)) as connection:
                connection.execute(f"PRAGMA application_id={project_container.APPLICATION_ID}")
                connection.execute("PRAGMA user_version=1")
                connection.execute("CREATE TABLE entries (path TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                                   "compression TEXT NOT NULL CHECK(compression IN ('none','deflate')), "
                                   "original_size INTEGER NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL)")
                for name, content in (("project.json", b'{"title":"old"}'), ("take.wav", payload)):
                    connection.execute("INSERT INTO entries VALUES (?, 'file', 'deflate', ?, ?, ?)",
                                       (name, len(content), hashlib.sha256(content).hexdigest(), zlib.compress(content)))
                connection.commit()
            project_container.extract_container(container, base / "opened")
            (source / "project.json").write_bytes(b'{"title":"new"}' * 100)
            with patch.object(project_container, "_publish_stage", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    project_container.sync_container(container, source)
            with closing(project_container._connect(container, readonly=True)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
            project_container.sync_container(container, source)
            with closing(project_container._connect(container, readonly=True)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(dict(connection.execute("SELECT path, compression FROM entries"))["take.wav"], "deflate")
                self.assertEqual(dict(connection.execute("SELECT path, compression FROM entries"))["project.json"], "zstd")
            project_container.extract_container(container, base / "updated")
            self.assertEqual((base / "updated/take.wav").read_bytes(), payload)

    def test_v2_file_with_legacy_compression_constraint_is_repaired_before_save(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "saved.scena"
            source.mkdir()
            original = b'{"title":"old"}'
            changed = b'{"title":"changed"}' * 100
            (source / "project.json").write_bytes(changed)
            with closing(project_container._connect(container)) as connection:
                connection.execute(f"PRAGMA application_id={project_container.APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version={project_container.FORMAT_VERSION}")
                connection.execute(
                    "CREATE TABLE entries (path TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                    "compression TEXT NOT NULL CHECK(compression IN ('none','deflate')), "
                    "original_size INTEGER NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO entries VALUES ('project.json', 'file', 'deflate', ?, ?, ?)",
                    (len(original), hashlib.sha256(original).hexdigest(), zlib.compress(original)),
                )
                connection.commit()

            project_container.sync_container(container, source)

            with closing(project_container._connect(container, readonly=True)) as connection:
                schema = connection.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='entries'"
                ).fetchone()[0]
                method = connection.execute(
                    "SELECT compression FROM entries WHERE path='project.json'"
                ).fetchone()[0]
            self.assertIn("zstd", schema)
            self.assertEqual(method, "zstd")
            project_container.extract_container(container, base / "updated")
            self.assertEqual((base / "updated/project.json").read_bytes(), changed)

    def test_compact_legacy_upgrade_reencodes_current_files_and_discards_derived_cache(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "saved.scena"
            cache = source / "media/cache/timeline-v1/old.wav"
            cache.parent.mkdir(parents=True)
            project = b'{"title":"current"}' * 100
            cached_audio = b"RIFF" + b"cache" * 1000
            (source / "project.json").write_bytes(project)
            cache.write_bytes(cached_audio)
            with closing(project_container._connect(container)) as connection:
                connection.execute(f"PRAGMA application_id={project_container.APPLICATION_ID}")
                connection.execute("PRAGMA user_version=1")
                connection.execute(
                    "CREATE TABLE entries (path TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                    "compression TEXT NOT NULL CHECK(compression IN ('none','deflate')), "
                    "original_size INTEGER NOT NULL, sha256 TEXT NOT NULL, data BLOB NOT NULL)"
                )
                for name, content in (("project.json", project), ("media/cache/timeline-v1/old.wav", cached_audio)):
                    connection.execute(
                        "INSERT INTO entries VALUES (?, 'file', 'deflate', ?, ?, ?)",
                        (name, len(content), hashlib.sha256(content).hexdigest(), zlib.compress(content)),
                    )
                connection.commit()

            project_container.sync_container(
                container, source, include_derived_audio=False, compact=True
            )

            with closing(project_container._connect(container, readonly=True)) as connection:
                entries = dict(connection.execute("SELECT path, compression FROM entries"))
            self.assertEqual(entries["project.json"], "zstd")
            self.assertNotIn("media/cache/timeline-v1/old.wav", entries)
            self.assertFalse(project_container.container_requires_upgrade(container))

    def test_v2_container_with_retained_deflate_entry_requires_upgrade(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            container = Path(raw) / "saved.scena"
            payload = b'{"title":"legacy blob"}'
            with closing(project_container._connect(container)) as connection:
                project_container._create_schema(connection)
                connection.execute(
                    "INSERT INTO entries VALUES ('project.json', 'file', 'deflate', ?, ?, ?)",
                    (len(payload), hashlib.sha256(payload).hexdigest(), zlib.compress(payload)),
                )
                connection.commit()

            self.assertTrue(project_container.container_requires_upgrade(container))

    def test_zstd_rejects_corruption_truncation_trailing_data_size_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "saved.scena"
            source.mkdir()
            (source / "project.json").write_bytes(b"x" * 1000)
            project_container.sync_container(container, source)
            pristine = container.read_bytes()
            for mutation in ("corrupt", "truncated", "trailing", "size", "hash"):
                with self.subTest(mutation=mutation):
                    container.write_bytes(pristine)
                    with closing(project_container._connect(container)) as connection:
                        row = connection.execute("SELECT data, original_size FROM entries WHERE path='project.json'").fetchone()
                        data = bytes(row[0])
                        if mutation == "corrupt":
                            connection.execute("UPDATE entries SET data=?", (b"bad" + data[3:],))
                        elif mutation == "truncated":
                            connection.execute("UPDATE entries SET data=?", (data[:-1],))
                        elif mutation == "trailing":
                            connection.execute("UPDATE entries SET data=?", (data + b"trailing",))
                        elif mutation == "size":
                            connection.execute("UPDATE entries SET original_size=?", (row[1] - 1,))
                        else:
                            connection.execute("UPDATE entries SET sha256=?", ("0" * 64,))
                        connection.commit()
                    with self.assertRaises(HTTPException):
                        project_container.extract_container(container, base / "out")

    def test_prepared_first_save_copies_only_recorded_files_and_checks_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, prepared, container = base / "scratch", base / "prepared", base / "saved.scena"
            source.mkdir()
            (source / "project.json").write_bytes(b'{"version":1}')
            (source / "media/takes").mkdir(parents=True)
            (source / "media/cache/waves").mkdir(parents=True)
            (source / "media/takes/a.wav").write_bytes(b"take" * 1000)
            (source / "media/cache/waves/a.bin").write_bytes(b"cache" * 1000)
            (source / "tts").mkdir()
            (source / "tts/model.bin").write_bytes(b"private")
            project_container.sync_container(container, source, root_entries=frozenset({"project.json", "media"}))
            project_container.prepare_saved_workspace(container, source, prepared)
            for relative in ("project.json", "media/takes/a.wav", "media/cache/waves/a.bin"):
                self.assertEqual((prepared / relative).read_bytes(), (source / relative).read_bytes())
            self.assertFalse((prepared / "tts").exists())
            self.assertIsNotNone(project_container._load_sync_index(container, prepared))

            (source / "media/takes/a.wav").write_bytes(b"other" * 800)
            with self.assertRaises(HTTPException):
                project_container.prepare_saved_workspace(container, source, base / "rejected")

    def test_root_entry_filter_excludes_application_data_from_first_save(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, extracted, container = base / "scena-data", base / "out", base / "test.scena"
            source.mkdir()
            (source / "project.json").write_text("{}", encoding="utf-8")
            (source / "media/takes").mkdir(parents=True)
            (source / "media/takes/take.wav").write_bytes(b"RIFFproject")
            (source / "tts/models").mkdir(parents=True)
            (source / "tts/models/model.bin").write_bytes(b"application-wide")
            (source / "global-characters").mkdir()
            (source / "global-characters/characters.json").write_text("[]", encoding="utf-8")

            project_container.sync_container(
                container,
                source,
                root_entries=frozenset({"project.json", "media"}),
            )
            project_container.extract_container(container, extracted)

            self.assertTrue((extracted / "project.json").is_file())
            self.assertEqual((extracted / "media/takes/take.wav").read_bytes(), b"RIFFproject")
            self.assertFalse((extracted / "tts").exists())
            self.assertFalse((extracted / "global-characters").exists())

    def test_windows_sync_fsyncs_through_a_writable_descriptor(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, container = base / "source", base / "test.scena"
            source.mkdir()
            (source / "project.json").write_text("{}", encoding="utf-8")

            project_container.sync_container(container, source)
            (source / "project.json").write_text('{"updated":true}', encoding="utf-8")
            project_container.sync_container(container, source)

            self.assertTrue(container.is_file())




if __name__ == "__main__":
    unittest.main()

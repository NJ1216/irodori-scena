from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app as _registered_app  # noqa: F401
from server.modules import constants, project_container


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

    def test_failed_transaction_leaves_previous_container_readable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            source, output, container = base / "source", base / "out", base / "test.scena"
            source.mkdir()
            (source / "project.json").write_text('{"title":"old"}')
            project_container.sync_container(container, source)
            (source / "project.json").write_text('{"title":"new"}')
            with (
                patch.object(project_container, "_write_blob", side_effect=OSError("disk failed")),
                self.assertRaises(OSError),
            ):
                project_container.sync_container(container, source)
            project_container.extract_container(container, output)
            self.assertEqual((output / "project.json").read_text(), '{"title":"old"}')

    def test_nonblocking_lock_rejects_a_second_owner(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.object(constants, "DATA_ROOT", Path(raw) / "data"):
            container = Path(raw) / "test.scena"
            container.write_bytes(b"placeholder")
            project_container.acquire_container_lock(container)
            try:
                from server.file_lock import lock_exclusive

                lock_path = (
                    constants.DATA_ROOT
                    / "project-locks"
                    / f"{hashlib.sha256(str(container.resolve()).encode()).hexdigest()}.lock"
                )
                with lock_path.open("a+b") as stream, self.assertRaises(BlockingIOError):
                    lock_exclusive(stream)
                project_container._locked_container = None
                with self.assertRaises(HTTPException) as raised:
                    project_container.acquire_container_lock(container)
                self.assertEqual(raised.exception.detail["code"], "project_locked")
            finally:
                project_container.release_container_lock()




if __name__ == "__main__":
    unittest.main()

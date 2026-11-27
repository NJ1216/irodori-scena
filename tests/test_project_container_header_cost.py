from __future__ import annotations

import scena_test_isolation  # noqa: F401
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from server.app import app as _registered_app  # noqa: F401
from server.modules import project_container


class HeaderCheckCostTests(unittest.TestCase):
    """Saving must not rescan the whole container; opening and validating still must."""

    def _saved(self, base: Path) -> tuple[Path, Path]:
        source, container = base / "source", base / "saved.scena"
        (source / "media/takes").mkdir(parents=True)
        (source / "project.json").write_bytes(b"{}")
        (source / "media/takes/a.wav").write_bytes(b"RIFF" + b"audio" * 1000)
        project_container.sync_container(container, source)
        return source, container

    def _deep_flags(self, action) -> list[bool]:
        real = project_container._validate_header
        flags: list[bool] = []

        def spy(connection, *, deep: bool = True):
            flags.append(deep)
            return real(connection, deep=deep)

        with patch.object(project_container, "_validate_header", side_effect=spy):
            action()
        return flags

    def test_project_entry_save_uses_the_shallow_header_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, container = self._saved(Path(raw))
            (source / "project.json").write_bytes(b'{"title":"changed"}')
            flags = self._deep_flags(lambda: self.assertTrue(project_container.sync_project_entry(container, source)))
            self.assertTrue(flags)
            self.assertFalse(any(flags))

    def test_full_save_of_a_current_container_uses_the_shallow_header_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, container = self._saved(Path(raw))
            (source / "project.json").write_bytes(b'{"title":"changed"}')
            flags = self._deep_flags(lambda: project_container.sync_container(container, source))
            self.assertTrue(flags)
            self.assertFalse(any(flags))

    def test_open_and_validation_keep_the_full_integrity_scan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _, container = self._saved(Path(raw))
            self.assertTrue(all(self._deep_flags(lambda: project_container.validate_container(container))))
            self.assertTrue(all(self._deep_flags(lambda: project_container.container_requires_upgrade(container))))

    def test_shallow_check_still_rejects_foreign_or_unsupported_headers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            _, container = self._saved(Path(raw))
            for pragma in ("application_id=1", "user_version=99"):
                with self.subTest(pragma=pragma):
                    with project_container._connect(container) as connection:
                        connection.execute(f"PRAGMA {pragma}")
                    with project_container._connect(container, readonly=True) as connection, self.assertRaises(HTTPException):
                        project_container._validate_header(connection, deep=False)
                    # restore for the next case
                    with project_container._connect(container) as connection:
                        connection.execute(f"PRAGMA application_id={project_container.APPLICATION_ID}")
                        connection.execute(f"PRAGMA user_version={project_container.FORMAT_VERSION}")


if __name__ == "__main__":
    unittest.main()

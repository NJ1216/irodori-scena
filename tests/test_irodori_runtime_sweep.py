from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import irodori_runtime_layout as layout

REPO = Path(__file__).resolve().parents[1]


def _make_dir(parent: Path, prefix: str, *, owner: dict | None = None, mtime: float | None = None) -> Path:
    path = Path(tempfile.mkdtemp(prefix=prefix, dir=parent))
    (path / "model.safetensors").write_bytes(b"x")
    if owner is not None:
        (path / layout.OWNER_MARKER).write_text(json.dumps(owner), encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


class RuntimeSweepTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.tmp = Path(self._temp.name) / "tmp"
        self.model = Path(self._temp.name) / "model"
        self.tmp.mkdir()
        self.model.mkdir()
        patcher = patch.object(layout.tempfile, "gettempdir", return_value=str(self.tmp))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_removes_dead_owner_dirs_and_keeps_live_owner_dirs(self) -> None:
        me = layout.psutil.Process()
        live = _make_dir(self.tmp, layout.TEMP_PREFIX, owner={"pid": me.pid, "createTime": me.create_time()})
        reused_pid = _make_dir(self.tmp, layout.TEMP_PREFIX, owner={"pid": me.pid, "createTime": me.create_time() - 500})
        dead = _make_dir(self.model, layout.ADJACENT_PREFIX, owner={"pid": 2**22 + 12345, "createTime": 1.0})

        removed = layout.sweep_stale_runtime_dirs(self.model)

        self.assertTrue(live.exists())
        self.assertFalse(reused_pid.exists())
        self.assertFalse(dead.exists())
        self.assertCountEqual(removed, [reused_pid, dead])

    def test_owner_that_cannot_be_inspected_is_treated_as_alive(self) -> None:
        me = layout.psutil.Process()
        guarded = _make_dir(self.tmp, layout.TEMP_PREFIX, owner={"pid": me.pid, "createTime": me.create_time()})
        for error in (layout.psutil.AccessDenied(me.pid), layout.psutil.Error("unreadable")):
            with self.subTest(error=type(error).__name__), patch.object(layout.psutil, "Process", side_effect=error):
                self.assertEqual(layout.sweep_stale_runtime_dirs(), [])
                self.assertTrue(guarded.exists())

    def test_unmarked_dir_is_removed_only_when_older_than_boot(self) -> None:
        boot = layout.psutil.boot_time()
        old = _make_dir(self.tmp, layout.TEMP_PREFIX, mtime=boot - 100)
        fresh = _make_dir(self.tmp, layout.TEMP_PREFIX, mtime=boot + 100)
        layout.sweep_stale_runtime_dirs()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_foreign_names_files_and_symlinks_are_never_touched(self) -> None:
        boot = layout.psutil.boot_time()
        stale = {"pid": 2**22 + 777, "createTime": 1.0}
        foreign = _make_dir(self.tmp, "other-runtime-", owner=stale, mtime=boot - 100)
        user_dir = _make_dir(self.model, "tokenizer-", owner=stale, mtime=boot - 100)
        plain_file = self.tmp / (layout.TEMP_PREFIX + "file")
        plain_file.write_text("x")
        target = _make_dir(self.model, "keep-", owner=stale)
        link = self.tmp / (layout.TEMP_PREFIX + "link")
        link.symlink_to(target, target_is_directory=True)

        layout.sweep_stale_runtime_dirs(self.model)

        for path in (foreign, user_dir, plain_file, target, link):
            self.assertTrue(path.exists() or path.is_symlink(), path)
        self.assertTrue((target / "model.safetensors").exists())

    def test_prepare_sweeps_stale_dirs_and_marks_its_own(self) -> None:
        stale = _make_dir(self.tmp, layout.TEMP_PREFIX, owner={"pid": 2**22 + 99, "createTime": 1.0})
        checkpoint = self.model / "float8" / "model.safetensors"
        tokenizer = self.model / "tokenizer"
        checkpoint.parent.mkdir()
        tokenizer.mkdir()
        checkpoint.write_bytes(b"m")
        staged = layout.prepare_runtime_checkpoint(checkpoint, tokenizer)
        try:
            self.assertFalse(stale.exists())
            self.assertTrue((staged.temporary_root / layout.OWNER_MARKER).is_file())
            # A second worker starting now must not delete this live worker's directory.
            layout.sweep_stale_runtime_dirs(self.model)
            self.assertTrue(staged.temporary_root.exists())
        finally:
            staged.cleanup()

    @unittest.skipUnless(hasattr(signal, "SIGTERM") and sys.platform != "win32", "POSIX signal semantics")
    def test_sigterm_runs_finally_cleanup_of_the_runtime_dir(self) -> None:
        script = (
            "import sys, time\n"
            "from pathlib import Path\n"
            "from server import irodori_runtime_layout as layout\n"
            "layout.install_termination_cleanup()\n"
            "root = Path(sys.argv[1])\n"
            "ck = root / 'v' / 'model.safetensors'; ck.parent.mkdir(); ck.write_bytes(b'm')\n"
            "tok = root / 'tokenizer'; tok.mkdir()\n"
            "staged = layout.prepare_runtime_checkpoint(ck, tok)\n"
            "try:\n"
            "    print(staged.temporary_root, flush=True)\n"
            "    time.sleep(60)\n"
            "finally:\n"
            "    staged.cleanup()\n"
        )
        env = {**os.environ, "TMPDIR": str(self.tmp), "PYTHONPATH": str(REPO)}
        process = subprocess.Popen([sys.executable, "-c", script, str(self.model)], stdout=subprocess.PIPE, text=True, env=env, cwd=REPO)
        try:
            staged_root = Path(process.stdout.readline().strip())
            self.assertTrue(staged_root.exists())
            process.terminate()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
        self.assertFalse(staged_root.exists())


if __name__ == "__main__":
    unittest.main()

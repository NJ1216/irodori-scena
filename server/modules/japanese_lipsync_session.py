"""One isolated Japanese worker per explicit export job, released on every exit."""
from __future__ import annotations

import json
import shutil
from server import subprocess_boundary as subprocess
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from server.registry import deps


class AddonSession:
    def __init__(self, command, manifest):
        self.command = command
        self.manifest = manifest
        self.directory = Path(tempfile.mkdtemp(prefix='scena-lipsync-session-'))
        self.process = None
        self.lock = threading.Lock()
        self.closed = False

    def _check(self, deadline, should_cancel):
        if should_cancel():
            raise deps.GenerationCancelled('エクスポートをキャンセルしました。')
        if self.closed or (self.process is not None and self.process.poll() is not None):
            raise RuntimeError('Japanese addon worker exited')
        if time.monotonic() >= deadline:
            raise RuntimeError('Japanese addon worker timed out')

    def _start(self, deadline, should_cancel):
        while not self.lock.acquire(timeout=.05):
            self._check(deadline, should_cancel)
        try:
            self._check(deadline, should_cancel)
            if self.process is None:
                self.process = subprocess.Popen([*self.command, '--serve', '--directory', str(self.directory)],
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        finally:
            self.lock.release()
        ready = self.directory / 'ready.json'
        while not ready.is_file():
            self._check(deadline, should_cancel)
            time.sleep(.02)
        identity = json.loads(ready.read_text(encoding='utf-8'))
        if any(identity.get(k) != self.manifest[k] for k in
               ('analysisVersion', 'modelSha256', 'processorSha256', 'textInfluence')):
            raise RuntimeError('Japanese worker identity mismatch')
        if ('executionSha256' in self.manifest
                and identity.get('executionSha256') != self.manifest['executionSha256']):
            raise RuntimeError('Japanese worker execution identity mismatch')

    def run(self, command, _cwd, timeout, should_cancel):
        try:
            return self._run(command, timeout, should_cancel)
        except (deps.GenerationCancelled, RuntimeError):
            self.close()
            raise

    def _run(self, command, timeout, should_cancel):
        deadline = time.monotonic() + timeout
        self._start(deadline, should_cancel)
        source = Path(command[command.index('--input') + 1])
        target = Path(command[command.index('--output') + 1])
        request_id = uuid.uuid4().hex
        pending = self.directory / (request_id + '.pending')
        request = self.directory / (request_id + '.request.json')
        result = self.directory / (request_id + '.result.json')
        pending.write_bytes(source.read_bytes())
        pending.replace(request)
        while not result.is_file():
            self._check(deadline, should_cancel)
            time.sleep(.02)
        self._check(deadline, should_cancel)
        target.write_bytes(result.read_bytes())
        result.unlink(missing_ok=True)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.process is not None:
                (self.directory / 'stop').touch()
                try:
                    self.process.wait(timeout=.25)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
            shutil.rmtree(self.directory, ignore_errors=True)


@contextmanager
def export_addon_session():
    from server.modules.japanese_lipsync_addon import _manifest
    session = None
    try:
        try:
            loaded = _manifest(deps.rhubarb_executable())
            if loaded is not None:
                manifest, worker, _ = loaded
                session = AddonSession([str(worker)], manifest)
                session.loaded_addon = loaded
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError):
            pass  # Missing/invalid enhancement keeps the existing Rhubarb path.
        yield session
    finally:
        if session is not None:
            session.close()

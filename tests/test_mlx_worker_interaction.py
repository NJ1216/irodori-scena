"""Exercise the desktop interaction signal against a real, inference-free worker."""
from __future__ import annotations

import json
import select
import signal
import subprocess
import sys
import unittest
from pathlib import Path


WORKER = Path(__file__).resolve().parents[1] / "server" / "mlx_irodori_worker.py"
HARNESS = """
import runpy
import sys
from types import SimpleNamespace

worker = runpy.run_path(sys.argv[1])
namespace = worker['main'].__globals__

class Model:
    def generate(self, **kwargs):
        print('generating', flush=True)
        assert sys.stdin.readline().strip() == 'continue'
        yield SimpleNamespace(audio=[], sample_rate=24000)

def load():
    print('loading', flush=True)
    assert sys.stdin.readline().strip() == 'continue'
    return Model()

namespace['_load_model'] = load
namespace['_write_wav'] = lambda path, audio, sample_rate: str(path)
worker['main']()
"""
REQUEST = {
    "operation": "synthesize", "text": "動作確認", "caption": None, "refWav": None,
    "output": "test.wav", "seed": 1, "numCandidates": 1, "steps": 16,
    "textCfg": 3, "voiceCfg": 5, "captionCfg": 3, "schedule": "sway", "durationScale": 1,
}


@unittest.skipUnless(hasattr(signal, "SIGUSR1"), "The desktop interaction signal is Unix-only")
class MlxWorkerInteractionTests(unittest.TestCase):
    def setUp(self):
        self.worker = subprocess.Popen(
            [sys.executable, "-u", "-c", HARNESS, str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8",
        )
        self.addCleanup(self.stop_worker)
        self.assertEqual(self.read_line(), "loading")

    def stop_worker(self):
        if self.worker.poll() is None:
            self.worker.kill()
        self.worker.communicate(timeout=5)

    def read_line(self):
        ready, _, _ = select.select([self.worker.stdout], [], [], 5)
        self.assertTrue(ready, "worker response timed out")
        return self.worker.stdout.readline().strip()

    def send(self, value):
        self.worker.stdin.write(value + "\n")
        self.worker.stdin.flush()

    def generate(self):
        self.send(json.dumps(REQUEST))
        self.assertEqual(self.read_line(), "generating")

    def finish_generation(self):
        self.send("continue")
        response = self.read_line()
        self.assertTrue(response.startswith("__SCENA_RESULT__"), response)
        self.assertTrue(json.loads(response.removeprefix("__SCENA_RESULT__"))["ok"])
        self.assertIsNone(self.worker.poll())

    def test_click_notification_during_model_loading_keeps_worker_alive(self):
        self.worker.send_signal(signal.SIGUSR1)
        self.send("continue")
        self.generate()
        self.finish_generation()

    def test_click_and_playback_notifications_do_not_interrupt_current_or_next_take(self):
        self.send("continue")
        for _ in range(2):
            self.generate()
            self.worker.send_signal(signal.SIGUSR1)
            self.finish_generation()

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import psutil

from server.modules.tts_environment_commands import EnvironmentCommandError, run_environment_command


class EnvironmentCommandTests(unittest.TestCase):
    def test_reports_bounded_actual_failure_instead_of_only_command(self):
        code = "import sys; sys.stderr.write('x'*10000+'\\nGit executable not found'); sys.exit(1)"
        with self.assertRaises(EnvironmentCommandError) as caught:
            run_environment_command([sys.executable, "-c", code], timeout=5)
        self.assertIn("Git executable not found", str(caught.exception))
        self.assertLessEqual(len(caught.exception.stderr), 6000)
        self.assertIsInstance(caught.exception, subprocess.SubprocessError)

    def test_success_does_not_publish_progress_output(self):
        self.assertIsNone(run_environment_command([sys.executable, "-c", "print('progress')"], timeout=5))

    def test_pre_cancelled_command_does_not_start(self):
        cancel = threading.Event()
        cancel.set()
        with patch("server.modules.tts_environment_commands.subprocess.Popen") as spawn:
            with self.assertRaises(InterruptedError):
                run_environment_command([sys.executable, "-c", "pass"], timeout=5, cancel=cancel)
        spawn.assert_not_called()

    def test_cancellation_stops_the_owned_command_and_its_child(self):
        self._assert_tree_stops(cancel_command=True)

    def test_timeout_stops_the_owned_command_and_its_child(self):
        self._assert_tree_stops(cancel_command=False)

    def _assert_tree_stops(self, *, cancel_command):
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / "child.pid"
            child_code = "import os,sys,time; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)"
            code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]]); time.sleep(30)"
            cancel = threading.Event()
            observed = threading.Event()

            def request_cancel():
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not ready.exists():
                    time.sleep(0.01)
                if ready.exists():
                    observed.set()
                    cancel.set()

            watcher = threading.Thread(target=request_cancel) if cancel_command else None
            if watcher:
                watcher.start()
            started = time.monotonic()
            try:
                with self.assertRaises(InterruptedError if cancel_command else subprocess.TimeoutExpired):
                    run_environment_command([sys.executable, "-c", code, str(ready), child_code],
                                            timeout=10 if cancel_command else 1, cancel=cancel)
                self.assertLess(time.monotonic() - started, 5)
                self.assertTrue(ready.is_file(), "the descendant must start before termination")
                if cancel_command:
                    self.assertTrue(observed.is_set())
                pid = int(ready.read_text())
                self.assertFalse(psutil.pid_exists(pid) and psutil.Process(pid).status() != psutil.STATUS_ZOMBIE)
            finally:
                if watcher:
                    watcher.join(timeout=4)
                if ready.exists():
                    try:
                        psutil.Process(int(ready.read_text())).kill()
                    except psutil.NoSuchProcess:
                        pass

    def test_only_windows_cuda_hosts_select_the_locked_cuda_extra(self):
        from unittest.mock import patch
        from server.modules.tts_environment_commands import inference_install_options
        with patch("server.modules.tts_environment_commands.os.name", "nt"):
            with patch("server.modules.tts_environment_commands.windows_cuda_device", return_value=True):
                self.assertEqual(inference_install_options(), (["--extra", "cu128"], "cuda-fp32-v1"))
            with patch("server.modules.tts_environment_commands.windows_cuda_device", return_value=False):
                self.assertEqual(inference_install_options(), ([], "cpu-fp32-v1"))
        with patch("server.modules.tts_environment_commands.os.name", "posix"):
            self.assertEqual(inference_install_options(), ([], None))

    def test_pre_volta_cuda_hosts_install_the_cpu_runtime(self):
        from unittest.mock import patch
        from server.modules.tts_environment_commands import inference_install_options
        with patch("server.modules.tts_environment_commands.os.name", "nt"), patch(
            "server.modules.tts_environment_commands.windows_cuda_device", return_value=True
        ):
            for capability, expected in [((6, 1), ([], "cpu-fp32-v1")), ((7, 0), (["--extra", "cu128"], "cuda-fp32-v1")), (None, (["--extra", "cu128"], "cuda-fp32-v1"))]:
                with self.subTest(capability=capability), patch(
                    "server.modules.tts_environment_commands.cuda_compute_capability", return_value=capability
                ):
                    self.assertEqual(inference_install_options(), expected)

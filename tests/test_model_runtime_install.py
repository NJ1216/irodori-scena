from __future__ import annotations

import scena_test_isolation  # noqa: F401
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from server.modules import omlx_environment as env


class ModelRuntimeInstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in [("_base", lambda: self.root / "runtime"),
                            ("_registry_path", lambda: self.root / "registry.json"),
                            ("_CANCEL", threading.Event()),
                            ("_JOB", {"id": "test", "runtimeId": "old", "state": "idle"})]:
            patcher = patch.object(env, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.spec = {"id": "old", "source": "scena", "requirements": "old-package==1", "launcher": "# old launcher",
                     "pythonVersion": "3.12", "importProbe": "import old_package", "omlxVersion": "1"}

    def test_install_uses_saved_artifacts_and_publishes_only_after_probe(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("", "")
        def verify(staging, *, probe):
            self.assertFalse((env._runtime_path("old") / ".ready").exists())
            self.assertEqual((staging / "scena-requirements.txt").read_text(), "old-package==1")
            self.assertEqual((staging / "scena-launcher.py").read_text(), "# old launcher")
            self.assertEqual(probe, "import old_package")
        with patch.object(env.subprocess, "run", return_value=Mock(stdout="old-package==1")), \
             patch.object(env.subprocess, "Popen", return_value=process) as install, \
             patch.object(env, "_verify", side_effect=verify), patch.object(env, "_installed_version", return_value="1"):
            env._run_install(self.spec)
        self.assertEqual(env._JOB["state"], "complete")
        self.assertIn("--no-deps", install.call_args.args[0])
        saved = env._read_registry()["runtimes"][0]["installSpec"]
        self.assertEqual(saved["requirements"], "old-package==1")
        self.assertEqual(saved["resolvedRequirements"], "old-package==1")
        self.assertTrue((env._runtime_path("old") / ".ready").is_file())

    def test_failed_probe_never_publishes_incomplete_environment(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("", "")
        with patch.object(env.subprocess, "run", return_value=Mock(stdout="old-package==1")), \
             patch.object(env.subprocess, "Popen", return_value=process), \
             patch.object(env, "_verify", side_effect=RuntimeError("health failed")):
            env._run_install(self.spec)
        self.assertEqual(env._JOB["state"], "failed")
        self.assertFalse(env._runtime_path("old").exists())
        self.assertEqual(env._read_registry()["runtimes"], [])

    def test_published_release_uses_its_dependencies_and_keeps_resolved_configuration(self):
        process = Mock(returncode=0)
        process.communicate.return_value = ("", "")
        spec = {**self.spec, "source": "github-release", "commit": "a" * 40}
        with patch.object(env.subprocess, "run", return_value=Mock(stdout="dependency==2")), \
             patch.object(env.subprocess, "Popen", return_value=process) as install, \
             patch.object(env, "_verify"), patch.object(env, "_installed_version", return_value="1"):
            env._run_install(spec)
        command = install.call_args.args[0]
        self.assertNotIn("--no-deps", command)
        self.assertEqual(command[-1], "git+https://github.com/jundot/omlx.git@" + "a" * 40)
        self.assertEqual(env._read_registry()["runtimes"][0]["installSpec"]["resolvedRequirements"], "dependency==2")

    def test_cancel_after_venv_does_not_start_dependency_download(self):
        def cancel(*_args, **_kwargs):
            env._CANCEL.set()
        with patch.object(env.subprocess, "run", side_effect=cancel), patch.object(env.subprocess, "Popen") as fetch:
            env._run_install(self.spec)
        fetch.assert_not_called()
        self.assertEqual(env._JOB["state"], "cancelled")
        self.assertFalse(env._runtime_path("old").exists())

import scena_test_isolation  # noqa: F401
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app_module  # noqa: F401
from server.modules import tts_downloads


class WindowsEngineInstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = {"engines": [], "models": [], "libraries": [],
                         "defaultEngineId": None, "defaultModelId": None}
        self.deps = SimpleNamespace(
            TTS_DOWNLOADS_ROOT=self.root / "downloads",
            TTS_ENGINES_ROOT=self.root / "engines",
            TTS_ENVIRONMENTS_ROOT=self.root / "environments",
            read_tts_registry=lambda: {key: list(value) if isinstance(value, list) else value
                                       for key, value in self.registry.items()},
            write_tts_registry=self._write_registry,
        )
        self.item = {
            "id": "engine", "displayName": "Irodori", "repo": "Aratako/Irodori-TTS",
            "commit": "commit", "pythonVersion": "3.10", "archiveUrl": "https://invalid.test/archive",
            "archiveSha256": "archive-sha", "dependencyLockSha256": "lock-sha",
            "optimizationProfile": "mps-fp32-v1", "license": "MIT", "licenseUrl": "https://invalid.test/license",
        }

    def _write_registry(self, registry):
        self.registry = registry

    @staticmethod
    def _download(_url, destination, _state, _cancel):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"archive")

    @staticmethod
    def _extract(_archive, destination):
        source = destination / "engine"
        source.mkdir(parents=True)
        (source / "infer.py").write_text("inference", encoding="utf-8")
        (source / "uv.lock").write_text("lock", encoding="utf-8")
        return source

    @staticmethod
    def _run(command, **_kwargs):
        if command[1] == "venv":
            environment = Path(command[-1])
            (environment / "Scripts").mkdir(parents=True)
            (environment / "Scripts/python.exe").write_text("python", encoding="utf-8")

    def _patch_install(self):
        return (
            patch.object(tts_downloads, "deps", self.deps),
            patch.object(tts_downloads, "is_windows", return_value=True),
            patch.object(tts_downloads, "_download_url", side_effect=self._download),
            patch.object(tts_downloads, "_safe_extract", side_effect=self._extract),
            patch.object(tts_downloads, "_sha256", side_effect=lambda path: "archive-sha" if path.name == "engine.tar.gz" else "lock-sha"),
            patch.object(tts_downloads, "_uv_binary", return_value="uv"),
            patch.object(tts_downloads, "run_environment_command", side_effect=self._run),
            patch.object(tts_downloads, "inference_install_options", return_value=(["--extra", "cu128"], "cuda-fp32-v1")),
            patch.object(tts_downloads.shutil, "disk_usage", return_value=SimpleNamespace(free=20 * 1024**3)),
            patch("server.modules.tts_install_placement.environment_python", side_effect=lambda path: path / "Scripts/python.exe"),
            patch.object(tts_downloads, "environment_python", side_effect=lambda path: path / "Scripts/python.exe"),
            patch.object(tts_downloads, "engine_environment_path", side_effect=lambda _staging, target: target),
        )

    def _install(self):
        patches = self._patch_install()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11]:
            tts_downloads._install_engine(self.item, {}, threading.Event())

    def test_registry_failure_rolls_back_promoted_engine_and_final_environment(self):
        self.deps.write_tts_registry = lambda _registry: (_ for _ in ()).throw(OSError("registry failed"))

        with self.assertRaisesRegex(OSError, "registry failed"):
            self._install()

        self.assertFalse((self.root / "engines/commit").exists())
        self.assertFalse((self.root / "environments/commit").exists())
        self.assertEqual(self.registry["engines"], [])

    def test_retry_recovers_unregistered_partial_paths_then_persists_resolvable_runtime(self):
        for path in (self.root / "engines/commit", self.root / "environments/commit"):
            path.mkdir(parents=True)
            (path / "partial").write_text("stale", encoding="utf-8")

        self._install()

        card = self.registry["engines"][0]
        self.assertEqual(card["optimizationProfile"], "cuda-fp32-v1")
        self.assertEqual(Path(card["path"]), self.root / "engines/commit")
        self.assertEqual(Path(card["pythonPath"]), self.root / "environments/commit/Scripts/python.exe")
        self.assertTrue(Path(card["path"], "infer.py").is_file())
        self.assertTrue(Path(card["pythonPath"]).is_file())

    def test_cancelling_environment_construction_never_publishes_the_engine(self):
        cancel = threading.Event()
        calls = []

        def run(command, **options):
            self.assertIs(options["cancel"], cancel)
            calls.append(command[1])
            self._run(command)
            if command[1] == "sync":
                cancel.set()
                raise InterruptedError

        patches = self._patch_install()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[7], patches[8], patches[9], patches[10], patches[11], \
                patch.object(tts_downloads, "run_environment_command", side_effect=run):
            with self.assertRaises(InterruptedError):
                tts_downloads._install_engine(self.item, {}, cancel)
        self.assertEqual(calls, ["venv", "sync"])
        self.assertEqual(self.registry["engines"], [])
        self.assertFalse((self.root / "engines/commit").exists())


if __name__ == "__main__":
    unittest.main()

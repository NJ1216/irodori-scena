from __future__ import annotations

import scena_test_isolation  # noqa: F401
import io
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app_module  # noqa: F401
from server.modules.tts_downloads import _download_hf_repo, _engine_venv_command, _ensure_mlx_environment, _safe_extract


class TtsDownloadSafetyTests(unittest.TestCase):
    def test_mlx_environment_forwards_cancellation_before_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cancel = threading.Event()
            calls = []

            def run(command, **options):
                self.assertIs(options["cancel"], cancel)
                calls.append(command[1])
                if command[1] == "pip":
                    cancel.set()
                    raise InterruptedError

            with patch("server.modules.tts_downloads.deps", SimpleNamespace(
                TTS_ENVIRONMENTS_ROOT=root / "environments", TTS_DOWNLOADS_ROOT=root / "downloads",
            )), patch("server.modules.tts_downloads._uv_binary", return_value="uv"), \
                    patch("server.modules.tts_downloads.run_environment_command", side_effect=run):
                with self.assertRaises(InterruptedError):
                    _ensure_mlx_environment({}, cancel)
            self.assertEqual(calls, ["venv", "pip"])
            self.assertFalse((root / "environments/mlx-audio-0.5.0").exists())

    def test_anime_allowlist_excludes_quantized_files_and_counts_only_allowed_bytes(self) -> None:
        siblings = [
            SimpleNamespace(rfilename="model.safetensors", size=100),
            SimpleNamespace(rfilename="tokenizer/tokenizer.json", size=20),
            SimpleNamespace(rfilename="tokenizer/tokenizer_config.json", size=3),
            SimpleNamespace(rfilename="README.md", size=7),
            SimpleNamespace(rfilename="quantized/Q4/model.safetensors", size=50),
        ]
        info = SimpleNamespace(sha="a" * 40, siblings=siblings)
        downloaded: list[str] = []
        state = {"totalBytes": 0, "downloadedBytes": 0}
        allowed = ["model.safetensors", "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json", "README.md"]
        with tempfile.TemporaryDirectory() as temporary, patch(
            "server.modules.tts_downloads._model_info_with_optional_token", return_value=(info, None)
        ), patch("server.modules.tts_downloads._download_file", side_effect=lambda _repo, name, *_args: downloaded.append(name)):
            _download_hf_repo("phasefield-audio/Irodori-TTS-v4.1-Anime", "a" * 40, Path(temporary), state, threading.Event(), allowed)
        self.assertEqual(downloaded, allowed)
        self.assertEqual(state["totalBytes"], 130)

    def test_windows_engine_environment_ignores_parent_project_and_replaces_stale_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = Path(temporary) / "environment"

            self.assertEqual(
                _engine_venv_command("uv", {"pythonVersion": "3.10"}, environment, "win32"),
                ["uv", "venv", "--no-project", "--clear", "--force", "--python", "3.10", str(environment)],
            )

    def test_macos_engine_environment_keeps_catalog_version_and_existing_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            environment = Path(temporary) / "environment"
            self.assertEqual(
                _engine_venv_command("uv", {"pythonVersion": "3.10"}, environment, "darwin"),
                ["uv", "venv", "--python", "3.10", str(environment)],
            )

    def test_safe_extract_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("engine/../../outside")
                info.size = 1
                bundle.addfile(info, io.BytesIO(b"x"))
            with self.assertRaises(ValueError):
                _safe_extract(archive, root / "output")
            self.assertFalse((root / "outside").exists())

    def test_safe_extract_rejects_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "link.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("engine/link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/tmp"
                bundle.addfile(info)
            with self.assertRaises(ValueError):
                _safe_extract(archive, root / "output")

    def test_full_repository_model_without_file_allowlist_finishes_registration(self):
        # The official PyTorch FP32 variant downloads the whole repository, so
        # its catalog item carries downloadFiles=None (not a missing key).
        from server.modules import tts_downloads as downloads

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "codecs" / "codec-rev").mkdir(parents=True)
            (root / "models").mkdir()
            (root / "codecs" / "codec-rev" / "weights.pth").write_bytes(b"codec")
            registry = {"engines": [], "models": [], "defaultModelId": "existing"}
            written = []

            def fake_download(repo, revision, target, state, cancel, files=None):
                self.assertIsNone(files)
                (target / "tokenizer").mkdir(parents=True)
                (target / "model.safetensors").write_bytes(b"x" * 7)

            item = {"id": "base@rev", "displayName": "Base", "repo": "org/base", "revision": "rev",
                    "codecRepo": "org/codec", "codecRevision": "codec-rev", "modelSha256": "ok", "codecSha256": "ok",
                    "downloadFiles": None, "variantId": "pytorch-fp32", "baseModelId": "base@rev",
                    "license": "MIT", "modelCardUrl": "https://example.invalid", **{key: None for key in (
                        "generation", "referenceVoice", "voiceDesign", "combinedReferenceCaption", "legacy",
                        "recommendedOrder", "flowParameterization", "fixedSteps", "supportsRuntimeCfg", "supportsQualityPresets")}}
            dependencies = SimpleNamespace(TTS_DOWNLOADS_ROOT=root / "downloads", TTS_MODELS_ROOT=root / "models",
                                           TTS_CODECS_ROOT=root / "codecs", read_tts_registry=lambda: registry,
                                           write_tts_registry=written.append)
            with patch.object(downloads, "deps", dependencies), patch.object(downloads, "_download_hf_repo", fake_download), \
                    patch.object(downloads, "_download_legacy_tokenizer"), patch.object(downloads, "_sha256", return_value="ok"):
                downloads._install_model(item, {}, threading.Event())

            variant = written[-1]["models"][0]["installedVariants"][0]
            self.assertEqual((variant["id"], variant["diskBytes"]), ("pytorch-fp32", 7))
            self.assertTrue((root / "models" / "rev" / "model.safetensors").is_file())


if __name__ == "__main__":
    unittest.main()

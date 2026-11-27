from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from fastapi import HTTPException

from server.modules import mtp_assets


class MtpAssetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch("server.modules.constants.LOCAL_LLM_ROOT", self.root)
        self.root_patch.start()

    def tearDown(self) -> None:
        self.root_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def metadata(*, revision: str = mtp_assets.MTP_TARGET_REVISION) -> dict[str, str]:
        return {"repoId": mtp_assets.MTP_TARGET_REPO, "revision": revision}

    def install_asset(self) -> None:
        root = mtp_assets.mtp_asset_root()
        root.mkdir(parents=True)
        (root / "config.json").write_text('{"model_type":"gemma4_assistant"}')
        (root / "model.safetensors").write_bytes(b"weights")
        (root / ".scena-mtp.json").write_text(json.dumps({
            "version": mtp_assets.MTP_ASSET_VERSION,
            "repo": mtp_assets.MTP_DRAFT_REPO,
            "revision": mtp_assets.MTP_DRAFT_REVISION,
        }))

    def test_exact_target_and_revision_are_required(self) -> None:
        self.assertTrue(mtp_assets.mtp_compatibility(self.metadata())["supported"])
        self.assertFalse(mtp_assets.mtp_compatibility(self.metadata(revision="main"))["supported"])
        self.assertFalse(mtp_assets.mtp_compatibility({"repoId": "other/model"})["supported"])

    def test_complete_hidden_asset_resolves(self) -> None:
        self.install_asset()
        resolved = mtp_assets.resolve_mtp_draft(self.metadata())
        self.assertEqual(resolved, mtp_assets.mtp_asset_root().resolve())
        self.assertIn(".runtime-assets/mtp", str(resolved))

    def test_incomplete_asset_cannot_enable_mtp(self) -> None:
        mtp_assets.mtp_asset_root().mkdir(parents=True)
        (mtp_assets.mtp_asset_root() / "config.json").write_text("{}")
        with self.assertRaises(HTTPException) as raised:
            mtp_assets.resolve_mtp_draft(self.metadata())
        self.assertEqual(raised.exception.status_code, 409)

    def test_assistant_revision_is_pinned(self) -> None:
        self.assertEqual(mtp_assets.MTP_DRAFT_REVISION, "627c5ec1458b9086b841a91e0512fd31fd2fbbf1")

    def test_status_reports_incomplete_asset_size(self) -> None:
        root = mtp_assets.mtp_asset_root()
        root.mkdir(parents=True)
        (root / "partial.safetensors").write_bytes(b"partial")
        status = mtp_assets.mtp_asset_status()
        self.assertFalse(status["installed"])
        self.assertEqual(status["diskBytes"], 7)
        self.assertFalse(status["cancelable"])

    def test_download_uses_shared_parallel_progress_downloader(self) -> None:
        files = [SimpleNamespace(rfilename="config.json", size=2),
                 SimpleNamespace(rfilename="model.safetensors", size=8)]
        state = {"state": "queued", "downloadedBytes": 0, "totalBytes": 0}

        def download(_repo: str, filename: str, _revision: str, root: Path,
                     progress: dict[str, object], _cancel: object, _token: str | None,
                     size: int) -> None:
            target = root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * size)
            progress["downloadedBytes"] = int(progress["downloadedBytes"]) + size

        with patch.object(mtp_assets, "HfApi") as api, patch.object(
                mtp_assets, "_download_file", side_effect=download) as shared_download:
            api.return_value.model_info.return_value = SimpleNamespace(siblings=files)
            mtp_assets._download(state, __import__("threading").Event())

        self.assertEqual(state["state"], "complete")
        self.assertEqual(state["downloadedBytes"], 10)
        self.assertEqual(shared_download.call_count, 2)
        self.assertEqual([call.args[-1] for call in shared_download.call_args_list], [2, 8])


if __name__ == "__main__":
    unittest.main()

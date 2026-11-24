from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server.modules import omlx_environment


class OmlxEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for target, value in [("server.modules.constants.LOCAL_LLM_ROOT", root),
                              ("server.modules.llm_registry.REGISTRY_FILE", root / "llm.json")]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fingerprint_uses_only_runtime_artifacts_shipped_in_app_bundle(self) -> None:
        manifest = Path("/bundle/requirements.txt")
        launcher = Path("/bundle/omlx-sidecar.py")
        with (
            patch.object(omlx_environment, "_manifest", return_value=manifest),
            patch.object(omlx_environment, "_launcher", return_value=launcher),
            patch.object(omlx_environment, "runtime_fingerprint", return_value="fingerprint") as fingerprint,
        ):
            self.assertEqual(omlx_environment._fingerprint(), "fingerprint")
        fingerprint.assert_called_once_with((manifest, launcher))

    def test_status_reuses_recorded_runtime_size(self) -> None:
        registry = {"activeRuntimeId": "active", "runtimes": [{
            "id": "active", "path": "/runtime/omlx-active", "state": "ready", "diskBytes": 123,
        }]}
        with (
            patch.object(omlx_environment, "_registry", return_value=registry),
            patch.object(omlx_environment, "_recommended_id", return_value="scena-test"),
            patch.object(omlx_environment, "runtime_catalog", return_value=[]),
            patch.object(omlx_environment.Path, "is_file", return_value=True),
            patch.object(omlx_environment, "_size") as size,
        ):
            status = omlx_environment.omlx_runtimes_status()
        self.assertEqual(status["installedRuntimes"][0]["diskBytes"], 123)
        size.assert_not_called()

    def test_existing_ready_environment_is_migrated_without_install(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "omlx-test-fingerprint"
            runtime.mkdir()
            (runtime / ".ready").write_text("legacy", encoding="utf-8")
            with (
                patch.object(omlx_environment, "_base", return_value=root),
                patch.object(omlx_environment, "_registry_path", return_value=root / "registry.json"),
                patch.object(omlx_environment, "_fingerprint", return_value="test-fingerprint"),
                patch.object(omlx_environment, "_installed_version", return_value="0.6.3"),
                patch.object(omlx_environment, "runtime_catalog", return_value=[]),
            ):
                status = omlx_environment.omlx_runtimes_status()
            self.assertEqual(status["activeRuntimeId"], "scena-test-fingerprint")
            self.assertEqual(status["installedRuntimes"][0]["omlxVersion"], "0.6.3")

    def test_release_list_excludes_drafts_and_marks_prereleases(self) -> None:
        values = [
            {"tag_name": "v1", "name": "Stable", "draft": False, "prerelease": False},
            {"tag_name": "v2rc", "draft": False, "prerelease": True},
            {"tag_name": "hidden", "draft": True, "prerelease": False},
        ]
        with patch.object(omlx_environment, "_github", return_value=values):
            releases = omlx_environment.list_omlx_releases()
        self.assertEqual([item["tag"] for item in releases], ["v1", "v2rc"])
        self.assertTrue(releases[1]["prerelease"])

    def test_release_tag_is_resolved_to_validated_commit(self) -> None:
        commit = "a" * 40
        responses = [
            {"tag_name": "v1", "draft": False},
            {"object": {"type": "tag", "sha": "b" * 40}},
            {"object": {"type": "commit", "sha": commit}},
        ]
        with patch.object(omlx_environment, "_github", side_effect=responses):
            _, resolved = omlx_environment._resolve_release("v1")
        self.assertEqual(resolved, commit)

    def test_recommended_version_tags_use_scena_manifest_install(self) -> None:
        for tag in ("0.6.4", "v0.6.4"):
            with self.subTest(tag=tag):
                with (
                    patch.object(omlx_environment, "_resolve_release") as resolve_release,
                    patch.object(omlx_environment, "_JOB", {"id": None, "runtimeId": None, "state": "idle", "message": ""}),
                    patch.object(omlx_environment, "runtime_catalog", return_value=[{"id": "scena-test", "omlxVersion": "0.6.4"}]),
                    patch.object(omlx_environment, "omlx_runtimes_status", return_value={"installedRuntimes": []}),
                    patch.object(omlx_environment.threading, "Thread") as thread,
                ):
                    omlx_environment.install_omlx_runtime(tag)
                resolve_release.assert_not_called()
                spec = thread.call_args.kwargs["args"][0]
                self.assertEqual(spec["source"], "scena")
                self.assertEqual(spec["omlxVersion"], "0.6.4")

    def test_missing_runtime_record_does_not_prevent_reinstall(self) -> None:
        missing = {"id": "scena-test", "state": "missing", "path": "/runtime/missing"}
        statuses = [
            {"installedRuntimes": [missing]},
            {"installedRuntimes": [missing], "job": {"state": "resolving"}},
        ]
        with (
            patch.object(
                omlx_environment,
                "_JOB",
                {"id": None, "runtimeId": None, "state": "idle", "message": ""},
            ),
            patch.object(
                omlx_environment,
                "runtime_catalog",
                return_value=[{"id": "scena-test", "omlxVersion": "0.6.4"}],
            ),
            patch.object(omlx_environment, "omlx_runtimes_status", side_effect=statuses),
            patch.object(omlx_environment.threading, "Thread") as thread,
        ):
            result = omlx_environment.install_omlx_runtime()
        thread.assert_called_once()
        thread.return_value.start.assert_called_once_with()
        self.assertEqual(result["job"]["state"], "resolving")

    def test_install_replaces_incomplete_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runtime"
            staging = Path(temporary) / "staging"
            root.mkdir()
            (root / "partial").write_text("incomplete", encoding="utf-8")
            staging.mkdir()
            (staging / ".ready").write_text("ready", encoding="utf-8")

            omlx_environment.activate_staging(staging, root)

            self.assertTrue((root / ".ready").is_file())
            self.assertFalse((root / "partial").exists())

    def test_duplicate_migrated_record_is_replaced_by_release_record(self) -> None:
        path = "/runtime/omlx-v1"
        registry = {
            "activeRuntimeId": "legacy-v1",
            "runtimes": [
                {"id": "legacy-v1", "path": path, "source": "migrated"},
                {"id": "release-v1", "path": path, "source": "github-release"},
            ],
        }
        changed = omlx_environment._normalize_registry(registry)
        self.assertTrue(changed)
        self.assertEqual(registry["activeRuntimeId"], "release-v1")
        self.assertEqual([item["id"] for item in registry["runtimes"]], ["release-v1"])

    def test_duplicate_symlinked_runtime_path_is_merged_with_the_scena_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = root / "data" / "runtime"
            runtime.mkdir(parents=True)
            alias = root / "application-support"
            alias.symlink_to(root / "data", target_is_directory=True)
            registry = {
                "activeRuntimeId": "legacy-runtime",
                "runtimes": [
                    {"id": "scena-runtime", "path": str(runtime), "source": "scena"},
                    {"id": "legacy-runtime", "path": str(alias / "runtime"), "source": "migrated"},
                ],
            }

            changed = omlx_environment._normalize_registry(registry)

        self.assertTrue(changed)
        self.assertEqual(registry["activeRuntimeId"], "scena-runtime")
        self.assertEqual([item["id"] for item in registry["runtimes"]], ["scena-runtime"])
        self.assertEqual(registry["runtimes"][0]["aliases"], ["legacy-runtime"])

    def test_delete_refuses_a_duplicate_record_that_resolves_to_a_shared_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime_root = root / "data" / "runtime"
            runtime = runtime_root / "omlx-shared"
            runtime.mkdir(parents=True)
            alias = root / "application-support"
            alias.symlink_to(root / "data", target_is_directory=True)
            registry = {
                "activeRuntimeId": "scena-runtime",
                "runtimes": [
                    {"id": "scena-runtime", "path": str(runtime), "source": "scena"},
                    {"id": "legacy-runtime", "path": str(alias / "runtime" / "omlx-shared"), "source": "migrated"},
                ],
            }
            with (
                patch.object(omlx_environment, "_registry", return_value=registry),
                patch.object(omlx_environment, "_base", return_value=runtime_root),
                patch.object(omlx_environment, "_write_registry") as write_registry,
                patch.object(omlx_environment.shutil, "rmtree") as remove_tree,
                patch("server.modules.llm_runtime_binding.deletion_reason", return_value=None),
            ):
                with self.assertRaises(omlx_environment.HTTPException) as raised:
                    omlx_environment.delete_omlx_runtime("legacy-runtime")

            self.assertEqual(raised.exception.status_code, 409)
            self.assertTrue(runtime.is_dir())
            remove_tree.assert_not_called()
            write_registry.assert_not_called()

    def test_active_runtime_can_be_deleted_without_deleting_models(self) -> None:
        registry = {"activeRuntimeId": "active", "runtimes": [{"id": "active", "path": "/runtime/omlx-active"}]}
        runtime_deps = Mock()
        with (
            patch.object(omlx_environment, "_registry", return_value=registry),
            patch.object(omlx_environment, "_write_registry") as write_registry,
            patch.object(omlx_environment, "omlx_runtimes_status", return_value={"activeRuntimeId": None}),
            patch.object(omlx_environment.shutil, "rmtree") as remove_tree,
            patch.object(omlx_environment, "deps", runtime_deps),
            patch.object(omlx_environment, "_base", return_value=Path("/runtime")),
            patch("server.modules.llm_runtime_binding.deletion_reason", return_value=None),
        ):
            result = omlx_environment.delete_omlx_runtime("active")
        self.assertEqual(result["activeRuntimeId"], None)
        self.assertEqual(registry, {"activeRuntimeId": None, "runtimes": []})
        runtime_deps.stop_local_llm.assert_not_called()
        remove_tree.assert_called_once_with(Path("/runtime/omlx-active"))
        write_registry.assert_called_once_with(registry)
        runtime_deps.read_llm_registry.assert_not_called()


if __name__ == "__main__":
    unittest.main()

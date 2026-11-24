from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from server.app import create_app
from server.modules import constants, project_container, project_repository, project_routes, workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app()

    def test_default_workspace_uses_scena_data_label(self) -> None:
        root = workspace.default_workspace_root()

        self.assertEqual(root.name, "scena-data")
        self.assertEqual(workspace.workspace_root_label(root), "scena-data（未保存）")

    def test_workspace_switch_is_rejected_while_synthesis_is_active(self) -> None:
        synthesis_lock = unittest.mock.Mock()
        synthesis_lock.locked.return_value = True
        with (
            patch("server.modules.export_service.active_draft_job", return_value=None),
            patch("server.modules.export_service.active_export_job", return_value=None),
            patch("server.modules.inference.INFERENCE_SYNTHESIS_LOCK", synthesis_lock),
        ):
            with self.assertRaises(HTTPException) as raised:
                project_routes.create_new_project()
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["code"], "operation_conflict")

    def test_shutdown_has_no_project_cleanup_hook(self) -> None:
        self.assertFalse(hasattr(project_routes, "shutdown_project"))

    def test_new_project_does_not_clean_up_previous_project(self) -> None:
        with (
            patch.object(project_routes, "_require_workspace_switch_available"),
            patch("server.modules.project_cache_cleanup.cleanup_loaded_project") as cleanup,
            patch("server.modules.inference.shutdown_inference_worker", side_effect=RuntimeError("stop transition")),
        ):
            with self.assertRaisesRegex(RuntimeError, "stop transition"):
                project_routes.create_new_project()
        cleanup.assert_not_called()

    def test_llm_debug_output_is_disabled_outside_development(self) -> None:
        with TemporaryDirectory() as directory, patch.object(
            constants, "LLM_DEBUG_ROOT", Path(directory) / "debug"
        ), patch.object(constants, "LLM_DEBUG_ENABLED", False):
            debug_directory = workspace.draft_debug_directory("draft-1")
            workspace.write_draft_debug_response(debug_directory / "attempt-1.txt", "response")

            self.assertFalse(debug_directory.exists())

    def test_startup_discards_restored_voice_design_candidates(self) -> None:
        project = {"candidates": [{"id": "candidate-1", "file": "candidate.wav"}]}
        with (
            patch("server.modules.project_repository.read_project", return_value=project),
            patch("server.modules.inference.clear_voice_candidates") as clear,
            patch("server.modules.project_repository.write_project") as write,
        ):
            workspace.discard_restored_voice_candidates()

        clear.assert_called_once_with(project)
        write.assert_called_once_with(project)

    def test_startup_does_not_rewrite_a_project_without_candidates(self) -> None:
        with (
            patch("server.modules.project_repository.read_project", return_value={"candidates": []}),
            patch("server.modules.inference.clear_voice_candidates") as clear,
            patch("server.modules.project_repository.write_project") as write,
        ):
            workspace.discard_restored_voice_candidates()

        clear.assert_not_called()
        write.assert_not_called()

    def test_llm_debug_output_is_written_in_development(self) -> None:
        with TemporaryDirectory() as directory, patch.object(
            constants, "LLM_DEBUG_ROOT", Path(directory) / "debug"
        ), patch.object(constants, "LLM_DEBUG_ENABLED", True):
            debug_directory = workspace.draft_debug_directory("draft-1")
            response_path = debug_directory / "attempt-1.txt"
            workspace.write_draft_debug_response(response_path, "response")

            self.assertEqual(response_path.read_text(encoding="utf-8"), "response")

    def test_internal_scena_data_cannot_be_a_project_destination(self) -> None:
        with TemporaryDirectory() as directory:
            data_root = Path(directory) / "scena-data"
            data_root.mkdir()
            with patch("server.modules.constants.DATA_ROOT", data_root):
                with self.assertRaisesRegex(HTTPException, "scena-data とその配下"):
                    workspace.require_external_project_destination(data_root / "projects")

    def test_first_save_only_packages_project_owned_root_entries(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            scratch = base / "scena-data"
            scratch.mkdir()
            destination = base / "saved.scena"
            project = workspace.default_project()
            workspace_result = {"path": str(destination), "name": destination.name, "isScratch": False}
            with (
                patch.object(constants, "DATA_ROOT", scratch),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", scratch),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.materialize_cast_global_characters", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.project_container.sync_container") as sync,
                patch("server.modules.project_container.container_signature", return_value=(1, 2, 3)),
                patch("server.modules.project_container.prepare_saved_workspace"),
                patch("server.modules.workspace.activate_project_container"),
                patch("server.modules.workspace.workspace_info", return_value=workspace_result),
            ):
                result = project_repository.move_scratch_project_to(destination)

            sync.assert_called_once_with(
                destination,
                scratch,
                root_entries=frozenset({"project.json", "media"}),
            )
            self.assertEqual(result["workspace"], workspace_result)
            self.assertTrue(result["moved"])

    def test_first_save_failure_keeps_scratch_and_removes_container(self) -> None:
        for failed_step in ("prepare", "activate"):
            with self.subTest(failed_step=failed_step), TemporaryDirectory() as directory:
                base = Path(directory)
                scratch, destination = base / "scena-data", base / "saved.scena"
                scratch.mkdir()
                (scratch / "project.json").write_text("{}")
                project = workspace.default_project()
                with (
                    patch.object(constants, "DATA_ROOT", scratch),
                    patch.object(constants, "ACTIVE_PROJECT_ROOT", scratch),
                    patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                    patch("server.modules.project_repository.read_project", return_value=project),
                    patch("server.modules.project_repository.materialize_cast_global_characters", return_value=project),
                    patch("server.modules.project_repository.write_project"),
                    patch("server.modules.workspace.activate_project_container", side_effect=OSError("switch failed") if failed_step == "activate" else None),
                    patch("server.modules.project_container.prepare_saved_workspace", side_effect=OSError("copy failed") if failed_step == "prepare" else None),
                ):
                    with self.assertRaises(HTTPException):
                        project_repository.move_scratch_project_to(destination)
                    self.assertIsNone(constants.ACTIVE_PROJECT_PATH)
                    self.assertEqual(constants.ACTIVE_PROJECT_ROOT, scratch)
                self.assertFalse(destination.exists())
                self.assertTrue((scratch / "project.json").exists())

    def test_saved_workspace_exposes_file_path_and_keeps_cache_private(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_tree = root / "source"
            source_tree.mkdir()
            (source_tree / "project.json").write_text("{}")
            container = root / "作品.scena"
            project_container.sync_container(container, source_tree)
            data_root = root / "app-support"
            with (
                patch.object(constants, "DATA_ROOT", data_root),
                patch.object(constants, "APP_STATE_FILE", data_root / "app-state.json"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", data_root),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(constants, "PROJECT_FILE", data_root / "project.json"),
                patch.object(constants, "MEDIA_ROOT", data_root / "media"),
            ):
                try:
                    workspace.activate_project_container(container)
                    info = workspace.workspace_info()
                    self.assertEqual(info, {"path": str(container.resolve()), "name": "作品.scena", "isScratch": False})
                    self.assertNotEqual(constants.ACTIVE_PROJECT_ROOT, container)
                    self.assertTrue(constants.ACTIVE_PROJECT_ROOT.is_relative_to(data_root / "project-workspaces"))
                finally:
                    project_container.release_container_lock()

    def test_prepared_activation_failure_restores_scratch_state(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            scratch, prepared, data_root = base / "scratch", base / "prepared", base / "data"
            scratch.mkdir()
            prepared.mkdir()
            (prepared / "project.json").write_text("{}")
            container = base / "saved.scena"
            project_container.sync_container(container, prepared)
            with (
                patch.object(constants, "DATA_ROOT", data_root),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", scratch),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(constants, "PROJECT_FILE", scratch / "project.json"),
                patch.object(constants, "MEDIA_ROOT", scratch / "media"),
                patch.object(workspace, "save_active_workspace_state", side_effect=OSError("persist failed")),
            ):
                with self.assertRaises(OSError):
                    workspace.activate_project_container(container, prepared_root=prepared)
                self.assertEqual(constants.ACTIVE_PROJECT_ROOT, scratch)
                self.assertIsNone(constants.ACTIVE_PROJECT_PATH)
                self.assertFalse(project_container.working_root(container).exists())
            project_container.release_container_lock()

    def test_preflight_workspace_is_activated_without_a_second_extraction(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            source, prepared = base / "source", base / "prepared"
            source.mkdir()
            prepared.mkdir()
            (source / "project.json").write_text("{}")
            (prepared / "project.json").write_text('{"preflight":true}')
            container = base / "作品.scena"
            project_container.sync_container(container, source)
            data_root = base / "app-support"
            with (
                patch.object(constants, "DATA_ROOT", data_root),
                patch.object(constants, "APP_STATE_FILE", data_root / "app-state.json"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", data_root),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(project_container, "extract_container") as extract,
            ):
                try:
                    workspace.activate_project_container(
                        container,
                        prepared_root=prepared,
                        expected_signature=project_container.container_signature(container),
                    )
                    extract.assert_not_called()
                    self.assertEqual((constants.ACTIVE_PROJECT_ROOT / "project.json").read_text(), '{"preflight":true}')
                finally:
                    project_container.release_container_lock()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from server import subprocess_boundary
from server.modules import llama_cpp_runtime


ROOT = Path(__file__).parents[1]


class ProcessBoundaryTests(unittest.TestCase):
    def test_windows_boundary_always_adds_create_no_window(self) -> None:
        with patch.object(subprocess_boundary.os, "name", "nt"):
            options = subprocess_boundary._hidden({"creationflags": 4})
        self.assertEqual(options["creationflags"], 4 | 0x08000000)

    def test_production_python_does_not_import_subprocess_directly(self) -> None:
        offenders = []
        for path in (ROOT / "server").rglob("*.py"):
            if path.name == "subprocess_boundary.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if any(
                isinstance(node, ast.Import) and any(alias.name == "subprocess" for alias in node.names)
                or isinstance(node, ast.ImportFrom) and node.module == "subprocess"
                for node in ast.walk(tree)
            ):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_desktop_topology_selects_cuda_without_probe(self) -> None:
        with patch.dict("os.environ", {"SCENA_ACCELERATOR_TOPOLOGY": '{"kind":"dedicated"}'}), patch.object(
            llama_cpp_runtime, "_cuda_driver_available"
        ) as driver:
            self.assertTrue(llama_cpp_runtime.nvidia_available())
        driver.assert_not_called()

    def test_system_only_topology_selects_cpu_without_probe(self) -> None:
        with patch.dict("os.environ", {"SCENA_ACCELERATOR_TOPOLOGY": '{"kind":"system-only"}'}), patch.object(
            llama_cpp_runtime, "_cuda_driver_available"
        ) as driver:
            self.assertFalse(llama_cpp_runtime.nvidia_available())
        driver.assert_not_called()

    def test_missing_or_broken_topology_uses_cuda_driver_api(self) -> None:
        for environment in ({}, {"SCENA_ACCELERATOR_TOPOLOGY": "{"}):
            with self.subTest(environment=environment), patch.dict("os.environ", environment, clear=True), patch.object(
                llama_cpp_runtime, "_cuda_driver_available", return_value=True
            ) as driver:
                self.assertTrue(llama_cpp_runtime.nvidia_available())
                driver.assert_called_once_with()

    def test_rust_windows_spawns_are_centralized(self) -> None:
        source = (ROOT / "src-tauri/src/api_supervisor_windows.rs").read_text(encoding="utf-8")
        self.assertEqual(source.count(".spawn()?"), 1)
        self.assertIn("hidden(&mut command);", source)
        self.assertIn("hidden(&mut command).status()?", source)
        self.assertNotIn('Command::new("taskkill.exe")\n            .args', source)


if __name__ == "__main__":
    unittest.main()

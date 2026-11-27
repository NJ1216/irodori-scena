from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
import ast
from pathlib import Path

from server.registry import DependencyRegistry, deps


class DependencyRegistryTests(unittest.TestCase):
    def test_application_dependency_references_resolve_to_loaded_owners(self) -> None:
        import server.app  # noqa: F401

        missing = []
        root = Path(__file__).resolve().parents[1] / "server"
        for path in root.rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "deps":
                    if not hasattr(deps, node.attr):
                        missing.append(f"{path.relative_to(root)}:{node.lineno}: {node.attr}")
        self.assertEqual(missing, [], "Dependency references must resolve without test doubles")

    def test_duplicate_owner_is_rejected_without_replacing_original(self) -> None:
        registry = DependencyRegistry()
        registry.register("server.modules.first", ["shared_name"])
        with self.assertRaisesRegex(RuntimeError, "already owned by server.modules.first"):
            registry.register("server.modules.second", ["shared_name"])
        self.assertEqual(registry._owners["shared_name"], "server.modules.first")

    def test_same_owner_can_repeat_registration(self) -> None:
        registry = DependencyRegistry()
        registry.register("server.modules.owner", ["stable_name"])
        registry.register("server.modules.owner", ["stable_name"])
        self.assertEqual(registry.names(), ("stable_name",))


if __name__ == "__main__":
    unittest.main()

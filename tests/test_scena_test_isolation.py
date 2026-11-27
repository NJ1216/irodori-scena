from __future__ import annotations

import scena_test_isolation  # noqa: F401
import ast
import os
import unittest
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = TESTS_ROOT.parent


def _imported_modules(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def _module_source(name: str) -> Path | None:
    for candidate in (REPOSITORY_ROOT / Path(*name.split("."))).with_suffix(".py"), TESTS_ROOT / f"{name}.py":
        if candidate.is_file():
            return candidate
    return None


def _imports_backend(tree: ast.AST, seen: set[str] | None = None) -> bool:
    """True when the module reaches ``server`` directly or through repository tools/test helpers."""
    seen = set() if seen is None else seen
    for name in _imported_modules(tree):
        if name == "scena_test_isolation":
            continue
        if name.split(".")[0] == "server":
            return True
        source = _module_source(name) if name.split(".")[0] in {"tools"} or "." not in name else None
        if source is not None and str(source) not in seen:
            seen.add(str(source))
            if _imports_backend(ast.parse(source.read_text(encoding="utf-8")), seen):
                return True
    return False


def _first_import(tree: ast.Module) -> str | None:
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        if isinstance(node, ast.Import):
            return node.names[0].name
        if isinstance(node, ast.ImportFrom):
            return node.module
    return None


class ScenaTestIsolationTests(unittest.TestCase):
    def test_every_backend_test_isolates_the_data_root_before_any_import(self) -> None:
        offenders = []
        for path in sorted(TESTS_ROOT.glob("*.py")):
            if path.name == "scena_test_isolation.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if _imports_backend(tree) and _first_import(tree) != "scena_test_isolation":
                offenders.append(path.name)
        self.assertEqual(offenders, [], "import scena_test_isolation before any other import")

    def test_backend_resolves_a_throwaway_data_root(self) -> None:
        from server.modules import constants

        real = (REPOSITORY_ROOT / "scena-data").resolve()
        self.assertEqual(os.environ["SCENA_DATA_ROOT"], scena_test_isolation.DATA_ROOT)
        self.assertEqual(constants.DATA_ROOT.resolve(), Path(scena_test_isolation.DATA_ROOT).resolve())
        self.assertNotEqual(constants.DATA_ROOT.resolve(), real)


if __name__ == "__main__":
    unittest.main()

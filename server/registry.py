from __future__ import annotations

import importlib
from typing import Any


class DependencyRegistry:
    """Resolve a symbol from its owning module at call time.

    Live resolution keeps unittest patches and mutable runtime ownership
    correct while mechanically separated services retain their call graph.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "_owners", {})

    def register(self, module_name: str, names: list[str]) -> None:
        for name in names:
            owner = self._owners.get(name)
            if owner is not None and owner != module_name:
                raise RuntimeError(
                    f"Backend dependency {name!r} is already owned by {owner}; "
                    f"duplicate registration from {module_name} is not allowed"
                )
            self._owners[name] = module_name

    def names(self) -> tuple[str, ...]:
        return tuple(self._owners)

    def __getattr__(self, name: str) -> Any:
        module_name = self._owners.get(name)
        if module_name is None:
            raise AttributeError(f"Backend dependency is not registered: {name}")
        return getattr(importlib.import_module(module_name), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_owners":
            object.__setattr__(self, name, value)
            return
        module_name = self._owners.get(name)
        if module_name is None:
            raise AttributeError(f"Backend dependency is not registered: {name}")
        setattr(importlib.import_module(module_name), name, value)


deps = DependencyRegistry()

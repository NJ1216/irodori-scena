"""Host capabilities; persisted provider identities remain portable."""
import sys

from fastapi import HTTPException


def require_builtin_llm() -> None:
    if sys.platform not in {"darwin", "win32"}:
        raise HTTPException(503, "SCENA内蔵LLMはmacOSまたはWindowsで利用できます。")


def environment_python(root):
    return root / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

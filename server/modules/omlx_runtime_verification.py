from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def runtime_fingerprint(paths) -> str:
    try:
        digest = hashlib.sha256()
        for path in paths:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()[:20]
    except OSError:
        return "unavailable"


def activate_staging(staging: Path, root: Path) -> None:
    if (root / ".ready").is_file():
        raise RuntimeError("同じ実行基盤がすでに存在します。")
    if root.exists():
        shutil.rmtree(root)
    staging.replace(root)


def runtime_import_probe() -> str:
    return (
        "import importlib.metadata as m;"
        "import mlx.core,mlx_lm,mlx_vlm,omlx,fastapi,uvicorn;"
        "from omlx._torch_stub import install as install_torch_stub;"
        "assert install_torch_stub();import xgrammar,tvm_ffi;"
        "assert m.version('xgrammar')=='0.2.3';"
        "assert m.version('apache-tvm-ffi')=='0.1.13.post3';"
        "assert hasattr(xgrammar,'GrammarCompiler');"
        "xgrammar.Grammar.from_json_schema('{\"type\":\"object\",\"properties\":{},"
        "\"additionalProperties\":false}');"
        "import torch;assert not m.packages_distributions().get('torch')"
    )

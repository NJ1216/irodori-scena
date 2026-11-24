from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
import platform
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.modules.huggingface_metadata import infer_local_model_tags
from server.registry import deps
from server.modules.llm_runtime_binding import serialized

SETTINGS_FILE = deps.DATA_ROOT / "local-llm-storage.json"
def _default_settings() -> dict[str, Any]:
    return {"libraries": []}


def _read_settings() -> dict[str, Any]:
    try:
        value = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return {**_default_settings(), **value} if isinstance(value, dict) else _default_settings()
    except (OSError, ValueError, json.JSONDecodeError):
        return _default_settings()


def _write_settings(value: dict[str, Any]) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(SETTINGS_FILE)


def local_llm_storage_root() -> Path:
    # Managed downloads have one application-owned location. Older storageRoot
    # and legacyRoots values are deliberately ignored and never migrated.
    return deps.LOCAL_LLM_ROOT


def _scan_library(root: Path, max_depth: int = 8, max_directories: int = 100_000) -> tuple[list[Path], bool, bool]:
    found: list[Path] = []
    stack = [(root, 0)]
    inspected = 0
    gguf_only = False
    while stack and inspected < max_directories:
        directory, depth = stack.pop()
        inspected += 1
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        names = {entry.name for entry in entries if entry.is_file(follow_symlinks=False)}
        if "config.json" in names and any(name.endswith(".safetensors") for name in names):
            found.append(directory.resolve())
            continue
        gguf_only |= any(name.endswith(".gguf") for name in names) or "blobs" in names
        if depth < max_depth:
            stack.extend((Path(entry.path), depth + 1) for entry in entries if entry.is_dir(follow_symlinks=False))
    return found, bool(stack), gguf_only


def _external_id(path: Path) -> str:
    return "external-" + hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()[:24]


def scan_external_llm_folder(path_value: str) -> dict[str, Any]:
    if platform.system() == "Windows":
        return deps.scan_gguf_folder(path_value)
    path = Path(path_value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise HTTPException(status_code=422, detail="外部モデルの親フォルダが見つかりません。")
    models, limited, gguf = _scan_library(path.resolve())
    return {"models": [{"id": _external_id(model), "displayName": model.name, "path": str(model),
                        "inferredTags": infer_local_model_tags(model)} for model in models],
            "limited": limited, "ggufFound": gguf}


@serialized
def register_external_llm_model(path_value: str) -> dict[str, Any]:
    if platform.system() == "Windows":
        return deps.register_external_gguf_model(path_value)
    path = Path(path_value).expanduser()
    if not path.is_absolute() or not path.is_dir() or path.is_symlink():
        raise HTTPException(status_code=422, detail="外部MLXモデルフォルダが見つかりません。")
    canonical = path.resolve()
    names = {item.name for item in canonical.iterdir() if item.is_file()}
    if "config.json" not in names or not any(name.endswith(".safetensors") for name in names):
        raise HTTPException(status_code=422, detail="config.jsonとsafetensorsを持つMLX候補を選択してください。")
    settings = _read_settings()
    model_id = _external_id(canonical)
    library = next((item for item in settings["libraries"] if item.get("path") == str(canonical.parent)), None)
    if library is None:
        library = {"id": "library-" + hashlib.sha256(str(canonical.parent).encode()).hexdigest()[:16],
                   "name": canonical.parent.name, "path": str(canonical.parent), "models": [], "warning": None}
        settings["libraries"].append(library)
    library["models"] = [item for item in library.get("models", []) if item.get("id") != model_id]
    library["models"].append({"id": model_id, "path": str(canonical), "displayName": canonical.name})
    _write_settings(settings)
    rebuild_local_llm_discovery()
    disk_bytes = sum(item.stat().st_size for item in canonical.rglob("*") if item.is_file())
    try:
        config = json.loads((canonical / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        config = {}
    quant = config.get("quantization") or config.get("quantization_config") or {}
    quantization = str(quant.get("bits") or quant.get("quant_method") or "") if isinstance(quant, dict) else str(quant)
    inferred_tags = infer_local_model_tags(canonical)
    card = deps.register_local_llm_card(model_id, source="external", metadata={
        "displayName": canonical.name, "path": str(canonical), "format": "MLX", "diskBytes": disk_bytes,
        "quantization": quantization or None,
        "inferredTags": inferred_tags,
        "fingerprint": hashlib.sha256("\n".join(f"{item.relative_to(canonical)}:{item.stat().st_size}:{item.stat().st_mtime_ns}"
                                                   for item in sorted(canonical.rglob("*")) if item.is_file()).encode()).hexdigest(),
    })
    return {"card": card, "model": {"id": model_id, "path": str(canonical), "displayName": canonical.name}}


def rebuild_local_llm_discovery() -> Path:
    discovery = deps.LOCAL_LLM_ROOT / "discovery"
    temporary = deps.LOCAL_LLM_ROOT / f".discovery-{uuid.uuid4().hex}"
    temporary.mkdir(parents=True, exist_ok=True)
    sources: list[tuple[str, Path]] = []
    settings = _read_settings()
    for library in settings["libraries"]:
        sources.extend((model["id"], Path(model["path"])) for model in library.get("models", []))
    linked: set[str] = set()
    for name, source in sources:
        if name in linked:
            continue
        if source.is_dir() and not source.is_symlink():
            (temporary / name).symlink_to(source, target_is_directory=True)
            linked.add(name)
    if discovery.exists() or discovery.is_symlink():
        old = deps.LOCAL_LLM_ROOT / f".discovery-old-{uuid.uuid4().hex}"
        discovery.replace(old)
        temporary.replace(discovery)
        shutil.rmtree(old, ignore_errors=True)
    else:
        temporary.replace(discovery)
    return discovery


def external_local_llm_models() -> list[dict[str, Any]]:
    result = []
    for library in _read_settings()["libraries"]:
        available_library = Path(library["path"]).is_dir()
        for model in library.get("models", []):
            available = available_library and Path(model["path"]).is_dir()
            result.append({"id": model["id"], "displayName": model["displayName"], "backend": "omlx",
                           "source": "external", "libraryName": library["name"], "pathAvailable": available,
                           "compatibility": "unverified", "installed": available})
    return result


deps.register(__name__, ["external_local_llm_models", "local_llm_storage_root", "rebuild_local_llm_discovery",
                         "register_external_llm_model", "scan_external_llm_folder"])

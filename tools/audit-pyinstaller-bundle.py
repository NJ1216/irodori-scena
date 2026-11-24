#!/usr/bin/env python3
"""Audit the contents hidden inside a PyInstaller one-file executable."""

import argparse
import ast
import hashlib
import json
from collections import defaultdict
from pathlib import Path

LARGE_FILE_BYTES = 10 * 1024 * 1024
FORBIDDEN_PARTS = {
    "av", "cryptography", "cv2", "datasets", "docling", "fitz", "librosa", "markitdown",
    "hf_xet", "mlx", "mlx_audio", "mlx_lm", "mlx_vlm", "mlx_whisper", "numpy", "omlx",
    "onnx", "onnxruntime", "openpyxl", "pandas", "pil", "polars", "pyarrow",
    "pydub", "pdfminer", "pypdfium2", "pyopenjtalk", "rerankers",
    "safetensors", "scipy", "sounddevice", "tensorflow", "torch",
    "torchaudio", "torchvision", "transformers", "video_reader", "watchfiles", "weasyprint",
}
FORBIDDEN_NATIVE_PREFIXES = (
    "libarrow", "libparquet", "libavcodec", "libavdevice", "libavfilter",
    "libavformat", "libavutil", "libpostproc", "libswresample", "libswscale",
    "libx264", "libx265",
)
ROOT = Path(__file__).parents[1]
EXTERNAL_WORKER_ROOTS = ("irodori_worker.py",)
MACOS_EXTERNAL_ROOTS = (
    "mlx_irodori_worker.py",
    "lora_training_worker.py",
    "irodori_mps_adapter.py",
    "irodori_mps_sampler.py",
)


def normalized_parts(name: str) -> list[str]:
    normalized = name.replace("\\", "/").replace(".", "/")
    return [part.lower().replace("-", "_") for part in normalized.split("/")]


def forbidden_entries(names: list[str]) -> list[str]:
    rejected = []
    for name in names:
        slash_name = name.replace("\\", "/")
        parts = normalized_parts(name)
        package_root = parts[0]
        directory_parts = [part.lower().replace("-", "_") for part in slash_name.split("/")[:-1]]
        basename = slash_name.rsplit("/", 1)[-1].lower()
        if package_root in FORBIDDEN_PARTS or any(part in FORBIDDEN_PARTS for part in directory_parts):
            rejected.append(name)
        elif basename.startswith(FORBIDDEN_NATIVE_PREFIXES):
            rejected.append(name)
    return sorted(set(rejected))


def external_worker_source_files(*, include_macos: bool = True) -> set[str]:
    """Find repository modules imported by source run in the managed TTS Python."""
    server = ROOT / "server"
    pending = [*EXTERNAL_WORKER_ROOTS, *(MACOS_EXTERNAL_ROOTS if include_macos else ())]
    required: set[str] = set()
    while pending:
        name = pending.pop()
        relative = f"server/{name}"
        if relative in required:
            continue
        path = server / name
        if not path.is_file():
            raise FileNotFoundError(f"external worker source is missing: {relative}")
        required.add(relative)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            modules = [node.module] if isinstance(node, ast.ImportFrom) else (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            )
            for module in modules:
                candidate = server / f"{str(module).removeprefix('server.').replace('.', '/')}.py"
                if candidate.parent == server and candidate.is_file():
                    pending.append(candidate.name)
    return required


def missing_external_worker_files(names: list[str], *, include_macos: bool = True) -> list[str]:
    normalized = [name.replace("\\", "/") for name in names]
    required_files = external_worker_source_files(include_macos=include_macos)
    return sorted(
        required for required in required_files
        if not any(name == required or name.endswith(f"/{required}") for name in normalized)
    )


def audit(path: Path) -> dict[str, object]:
    from PyInstaller.archive.readers import CArchiveReader

    executable = path / ("scena-api.exe" if (path / "scena-api.exe").is_file() else "scena-api") if path.is_dir() else path
    disk_files = [item for item in path.rglob("*") if item.is_file()] if path.is_dir() else [path]
    disk_names = [str(item.relative_to(path)).replace("\\", "/") for item in disk_files] if path.is_dir() else []
    archive = CArchiveReader(str(executable))
    names = list(archive.toc)
    pyz = next((name for name, entry in archive.toc.items() if entry[-1] == "z"), None)
    python_modules: list[str] = []
    if pyz:
        python_modules = list(archive.open_embedded_archive(pyz).toc)
    all_names = names + python_modules + disk_names
    large = {
        name: entry for name, entry in archive.toc.items()
        if entry[2] >= LARGE_FILE_BYTES and entry[-1] not in {"z", "Z"}
    }
    hashes: dict[tuple[int, str], list[str]] = defaultdict(list)
    for name, entry in large.items():
        hashes[(entry[2], hashlib.sha256(archive.extract(name)).hexdigest())].append(name)
    duplicates = [sorted(group) for group in hashes.values() if len(group) > 1]
    largest = sorted(archive.toc.items(), key=lambda item: item[1][1], reverse=True)[:20]
    return {
        "path": str(path),
        "bytes": sum(item.stat().st_size for item in disk_files),
        "largestArchiveEntries": [
            {"compressedBytes": entry[1], "uncompressedBytes": entry[2], "path": name}
            for name, entry in largest
        ],
        "forbiddenEntries": forbidden_entries(all_names),
        "missingExternalWorkerFiles": missing_external_worker_files(names + disk_names, include_macos=executable.suffix != ".exe"),
        "duplicateLargeEntries": duplicates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--max-bytes", type=int)
    args = parser.parse_args()
    result = audit(args.executable)
    if args.max_bytes is not None:
        result["maximumBytes"] = args.max_bytes
    print(json.dumps(result, ensure_ascii=False, indent=2))
    oversized = args.max_bytes is not None and result["bytes"] > args.max_bytes
    failed = (
        result["forbiddenEntries"]
        or result["missingExternalWorkerFiles"]
        or result["duplicateLargeEntries"]
        or oversized
    )
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()

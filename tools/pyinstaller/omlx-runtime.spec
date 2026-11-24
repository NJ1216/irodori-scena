# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller allowlist for the SCENA-owned oMLX serving boundary."""

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = Path(SPECPATH).parents[1]

site_root = next(
    Path(entry) for entry in sys.path
    if (Path(entry) / "omlx").is_dir() and (Path(entry) / "mlx_lm").is_dir()
)


def modules_below(package):
    base = site_root / package.replace(".", "/")
    return [
        ".".join((package, *path.relative_to(base).with_suffix("").parts))
        for path in base.rglob("*.py") if path.name != "__init__.py"
    ]


def transformer_loader_modules():
    base = site_root / "transformers" / "models"
    prefixes = ("configuration_", "processing_", "tokenization_")
    return [
        ".".join(("transformers.models", *path.relative_to(base).with_suffix("").parts))
        for path in base.rglob("*.py") if path.name.startswith(prefixes)
    ]


# Model implementations are selected dynamically from config.json. Enumerate
# source files without importing MLX during the build (headless builders have no
# Metal device). This preserves all loaders in the locked revisions.
hiddenimports = []
for package in (
    "mlx", "mlx_lm.models", "mlx_lm.chat_templates", "mlx_vlm.models",
    "omlx.adapter", "omlx.cache", "omlx.custom_kernels", "omlx.patches",
    "omlx.speculative", "omlx.specprefill",
):
    hiddenimports.extend(modules_below(package))
hiddenimports.extend(transformer_loader_modules())
hiddenimports.extend(modules_below("xgrammar"))
hiddenimports.extend(modules_below("tvm_ffi"))

# Runtime data only: tokenizer metadata and oMLX calibration tables. MLX's
# shader is deliberately placed beside the root-level libmlx.dylib exactly once.
mlx_root = site_root / "mlx"
datas = [
    (str(mlx_root / "lib" / "mlx.metallib"), "."),
    *collect_data_files("transformers", includes=["**/*.json"]),
    *collect_data_files("omlx", includes=["*_calibration_data.json"]),
    *collect_data_files("xgrammar"),
    *collect_data_files("tvm_ffi"),
]
binaries = [*collect_dynamic_libs("xgrammar"), *collect_dynamic_libs("tvm_ffi")]

excludedimports = [
    "av", "cv2", "datasets", "docling", "fitz", "librosa", "markitdown",
    # Pillow remains because the locked mlx-vlm package imports its Image
    # types while initializing Gemma 4 MTP, even for text-only requests.
    "mlx_audio", "mlx_whisper", "openpyxl", "pandas", "polars",
    "pyarrow", "pydub", "pdfminer", "pypdfium2", "rerankers", "sounddevice",
    "scipy", "torchaudio", "torchvision",
    "video_reader", "weasyprint",
    "omlx.admin", "omlx.api.audio_routes", "omlx.api.mcp_routes",
    "omlx.api.websearch_routes", "omlx.cluster", "omlx.eval", "omlx.integrations",
    "omlx.mcp", "omlx.websearch",
]

a = Analysis(
    [str(ROOT / "tools" / "omlx-sidecar.py")],
    pathex=[str(ROOT)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=excludedimports, noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="omlx-server", console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="omlx-server")

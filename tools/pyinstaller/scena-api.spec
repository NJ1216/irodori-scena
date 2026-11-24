# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller allowlist for the SCENA local orchestration API."""

from pathlib import Path
import os
import sys

ROOT = Path(SPECPATH).parents[1]
native_module_dir = os.environ.get("SCENA_NATIVE_MODULE_DIR") if sys.platform == "win32" else None
native_module = Path(native_module_dir).resolve() / "scena_native.pyd" if native_module_dir else None
if native_module and not native_module.is_file():
    raise FileNotFoundError(f"Release native module is missing: {native_module}")

# server.app owns a deliberate dynamic module registry. Keep that registry
# complete without collecting unrelated packages from the build environment.
hiddenimports = [
    f"server.modules.{path.stem}"
    for path in sorted((ROOT / "server" / "modules").glob("*.py"))
    if path.name != "__init__.py"
]
# The .scena reader/writer needs the compiled backend on both desktop platforms.
hiddenimports.append("zstandard.backend_c")
if sys.platform == "win32":
    hiddenimports.extend(["keyring.backends.Windows", "win32ctypes.pywin32.win32cred"])
else:
    hiddenimports.extend(["keyring.backends.macOS", "keyring.backends.macOS.api"])

# oMLX and MLX are installed on demand into a managed external environment.
datas = [
    # Rhubarb status is queried when the Settings page mounts on every desktop
    # platform. The frozen module cannot read this catalogue from the PYZ.
    (str(ROOT / "server" / "catalogs" / "rhubarb-runtime.json"), "server/catalogs"),
]
if sys.platform == "win32":
    # The frozen API reads this catalogue while coordinating llama.cpp and TTS
    # memory. Keep it available as an ordinary file outside the PYZ archive.
    datas.append((str(ROOT / "server" / "catalogs" / "llama-cpp-runtime.json"), "server/catalogs"))

# Irodori inference runs in its own selected Python environment. These small
# source files must therefore exist as ordinary files after one-file extraction;
# bytecode embedded in SCENA's Python archive is not visible to that interpreter.
datas.extend([
    (str(ROOT / "server" / "irodori_worker.py"), "server"),
    (str(ROOT / "server" / "irodori_runtime_layout.py"), "server"),
    (str(ROOT / "server" / "irodori_host.py"), "server"),
    (str(ROOT / "server" / "irodori_load_adapter.py"), "server"),
    (str(ROOT / "server" / "irodori_acceleration_adapter.py"), "server"),
    (str(ROOT / "server" / "irodori_acceleration_sampler.py"), "server"),
    (str(ROOT / "server" / "irodori_cuda_calibration.py"), "server"),
    (str(ROOT / "server" / "irodori_cuda_graphs.py"), "server"),
])
if sys.platform != "win32":
    datas.extend([
        (str(ROOT / "server" / "mlx_irodori_worker.py"), "server"),
        (str(ROOT / "server" / "mlx_acceleration_adapter.py"), "server"),
        (str(ROOT / "server" / "mlx_decode_compile.py"), "server"),
        (str(ROOT / "server" / "scena_mlx_lora.py"), "server"),
        (str(ROOT / "server" / "lora_training_worker.py"), "server"),
        (str(ROOT / "server" / "lora_training_compat.py"), "server"),
        (str(ROOT / "server" / "irodori_mps_adapter.py"), "server"),
        (str(ROOT / "server" / "irodori_mps_sampler.py"), "server"),
    ])

excludedimports = [
    "av", "cryptography", "cv2", "datasets", "docling", "fitz", "librosa", "markitdown",
    "mlx", "mlx_audio", "mlx_lm", "mlx_vlm", "mlx_whisper", "numpy", "omlx",
    "onnx", "onnxruntime", "openpyxl", "pandas", "polars", "pyarrow",
    "PIL", "pydub", "pdfminer", "pypdfium2", "pyopenjtalk", "rerankers",
    "safetensors", "scipy", "sounddevice", "tensorflow", "torch",
    "torchaudio", "torchvision", "transformers", "video_reader", "watchfiles", "weasyprint",
    # huggingface_hub uses hf_xet only for uploads; SCENA reads metadata and downloads with urllib.
    "hf_xet",
    # Interpreter tooling that the API never runs.
    "setuptools", "pkg_resources", "pydoc_data", "_pyrepl", "unittest",
    "keyring.backends.SecretService",
    "keyring.backends.chainer", "keyring.backends.kwallet",
    "keyring.backends.libsecret",
]
excludedimports.extend(
    ["keyring.backends.macOS", "keyring.backends.macOS.api"] if sys.platform == "win32"
    else ["keyring.backends.Windows", "win32ctypes"]
)

a = Analysis(
    [str(ROOT / "server" / "sidecar.py")],
    pathex=([str(native_module.parent)] if native_module else []) + [str(ROOT)], binaries=[], datas=datas,
    hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
    runtime_hooks=[], excludes=excludedimports, noarchive=False,
)
if native_module:
    native_entries = [index for index, (name, _, _) in enumerate(a.binaries) if Path(name).name.lower() == "scena_native.pyd"]
    if len(native_entries) != 1:
        raise RuntimeError(f"Expected one scena_native.pyd in PyInstaller analysis; found {len(native_entries)}")
    index = native_entries[0]
    name, _, kind = a.binaries[index]
    a.binaries[index] = (name, str(native_module), kind)
    if Path(a.binaries[index][1]).resolve() != native_module:
        raise RuntimeError(f"PyInstaller must collect the isolated native module {native_module}")
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="scena-api", console=sys.platform != "win32",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    name="scena-api", strip=False, upx=False,
)

"""Pinned CPU execution profiles; the reviewed v3 remains a separate identity."""
import hashlib
import importlib.metadata
import json
from pathlib import Path

V3_MODEL_SHA256 = 'ad29e980cb0f50044854bf25324506ace4ff0c48b98b4d194953028236c3ab6f'
COMMON_MODEL_SHA256 = '984fb84aa37b1e5dd9217c92cb8f3325fbbc19be52fc19c7e12a9bca349fba33'
COMMON_PROFILE = 'japanese-ctc-common-fp32-v4'
COMMON_ANALYSIS_VERSION = 'japanese-ctc-isolated-fallback-v7'
DEPENDENCIES = {'onnxruntime': '1.20.1', 'numpy': '2.3.5', 'scipy': '1.18.1'}


def model_hash(directory):
    digest = hashlib.sha256((directory / 'model_quantized.onnx').read_bytes()).hexdigest()
    if digest not in (V3_MODEL_SHA256, COMMON_MODEL_SHA256):
        raise ValueError('Unknown Japanese model execution profile')
    return digest


def common_execution(model_sha, runtime_root, *, threads, provider):
    if model_sha == V3_MODEL_SHA256:
        return {}
    if model_sha != COMMON_MODEL_SHA256 or threads != 2 or provider != 'CPUExecutionProvider':
        raise ValueError('Common Japanese profile requires its pinned model and CPU settings')
    versions = {name: importlib.metadata.version(name) for name in DEPENDENCIES}
    if versions != DEPENDENCIES:
        raise ValueError('Common Japanese profile dependency versions differ')
    root = Path(runtime_root)
    if (root / 'scena-runtime.json').exists():
        raise ValueError('Common Japanese profile requires unmodified upstream ORT')
    binaries = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((root / 'capi').iterdir())
                if path.is_file() and path.suffix.lower() in ('.pyd', '.dll', '.so', '.dylib')}
    if not binaries:
        raise ValueError('Missing common profile CPU runtime binaries')
    return {'modelExecutionProfile': COMMON_PROFILE, 'activationQuantization': 'none',
            'graphOptimization': 'ORT_ENABLE_ALL', 'dependencies': versions,
            'runtimeBinaries': binaries,
            'runtimeBinarySha256': hashlib.sha256(json.dumps(binaries, sort_keys=True).encode()).hexdigest()}

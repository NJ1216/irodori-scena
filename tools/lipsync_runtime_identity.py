"""Bind Windows cache/execution identity to actual ORT CPU library bytes."""
import hashlib
import json
from pathlib import Path


def binary_hashes(root):
    files = sorted(path for path in (root / 'capi').iterdir()
                   if path.is_file() and path.suffix.lower() in ('.pyd', '.dll'))
    if not any(path.name == 'onnxruntime_pybind11_state.pyd' for path in files):
        raise ValueError('Windows ONNX Runtime CPU binding is missing')
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files}


def windows_runtime_identity(root, version):
    root = Path(root)
    binaries = binary_hashes(root)
    metadata = root / 'scena-runtime.json'
    identity = {'runtimeBuild': 'upstream-' + version, 'runtimeBinaries': binaries}
    if metadata.is_file():
        declared = json.loads(metadata.read_text(encoding='utf-8'))
        if (declared['runtimeVersion'] != version or declared['binaryFiles'] != binaries
                or not declared['profile'] or not declared['sourceCommit']
                or not declared['patchedSourceSha256']):
            raise ValueError('Patched ONNX Runtime identity does not match CPU library bytes')
        identity.update(runtimeBuild=declared['profile'], runtimeSourceCommit=declared['sourceCommit'],
                        runtimePatchSha256=declared['patchedSourceSha256'],
                        runtimeMetadataSha256=hashlib.sha256(metadata.read_bytes()).hexdigest())
        options = declared.get('sessionOptions', {})
        if options not in ({}, {'session.x64quantprecision': '1'}):
            raise ValueError('Unsupported Windows Runtime session options')
        if options:
            identity['runtimeSessionOptions'] = options
    identity['runtimeBinarySha256'] = hashlib.sha256(json.dumps(binaries, sort_keys=True).encode()).hexdigest()
    return identity

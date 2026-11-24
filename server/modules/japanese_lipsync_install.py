"""Validate the optional packaged worker before committing an addon installation."""
from __future__ import annotations

import hashlib
import json
from server import subprocess_boundary as subprocess
import os
import shutil
import tempfile
from pathlib import Path

from server.modules.japanese_lipsync_addon import IDENTITY_FIELDS, _manifest


def installed_addon_status(rhubarb):
    try:
        loaded = _manifest(rhubarb, verify_package=False)
        if loaded is None:
            return None
        manifest, _, _ = loaded
        return {'ready': True, 'analysisVersion': manifest['analysisVersion'], 'license': 'Apache-2.0'}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def install_local_addon(source, rhubarb, platform_key, verify_architecture):
    """Atomically enable a verified local worker without replacing Rhubarb."""
    source, rhubarb = Path(source).resolve(), Path(rhubarb).resolve()
    if not rhubarb.is_file():
        raise ValueError('Install Rhubarb before its Japanese addon')
    manifest_path = source / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    from server.modules.japanese_lipsync_addon import verify_assets
    verify_assets(source, manifest['files'])
    target = rhubarb.parent / 'japanese-lipsync'
    lock = rhubarb.parent / '.japanese-lipsync-install.lock'
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with tempfile.TemporaryDirectory(prefix='.japanese-install-', dir=rhubarb.parent) as temporary:
            root = Path(temporary)
            staging = root / 'japanese-lipsync'
            staging.mkdir()
            for name in [*manifest['files'], 'manifest.json']:
                destination = staging / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / name, destination)
            entry = {'japaneseAddon': {'manifestSha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                                      'analysisVersion': manifest['analysisVersion'], 'license': 'Apache-2.0'}}
            status = verify_packaged_addon(root / rhubarb.name, entry, platform_key, verify_architecture)
            backup = root / 'previous'
            if target.is_symlink():
                raise ValueError('Unsafe installed Japanese addon path')
            if target.exists():
                os.replace(target, backup)
            try:
                os.replace(staging, target)
            except OSError:
                if backup.exists():
                    os.replace(backup, target)
                raise
            return status
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def verify_packaged_addon(rhubarb, entry, platform_key, verify_architecture):
    expected = entry.get('japaneseAddon')
    if expected is None:
        return None
    path = rhubarb.parent / 'japanese-lipsync/manifest.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected['manifestSha256']:
        raise ValueError('Japanese addon manifest hash mismatch')
    loaded = _manifest(rhubarb)
    if loaded is None:
        raise ValueError('Packaged Japanese addon is disabled')
    manifest, worker, _ = loaded
    if manifest['analysisVersion'] != expected['analysisVersion']:
        raise ValueError('Packaged Japanese analysis identity mismatch')
    worker.chmod(worker.stat().st_mode | 0o100)
    verify_architecture(worker, platform_key)
    result = subprocess.run([str(worker), '--self-test'], cwd=worker.parent, capture_output=True,
                            timeout=60, check=True, encoding='utf-8')
    identity = json.loads(result.stdout)
    if any(identity.get(key) != manifest[key] for key in (*IDENTITY_FIELDS, 'executionSha256')):
        raise ValueError('Japanese addon self-test identity mismatch')
    return {'analysisVersion': manifest['analysisVersion'], 'license': expected['license'],
            'executionSha256': manifest['executionSha256']}

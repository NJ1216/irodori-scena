"""Installed package identity and replacement of managed Rhubarb runtimes."""
import hashlib
import json
import os
import shutil
import uuid


def package_matches(root, entry):
    try:
        marker = json.loads((root / '.ready').read_text(encoding='utf-8'))
        expected = entry.get('japaneseAddon')
        if expected is None:
            return True
        if marker.get('archiveSha256') != entry['archiveSha256']:
            return False
        manifest = root / entry['executable']
        manifest = manifest.parent / 'japanese-lipsync/manifest.json'
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != expected['manifestSha256']:
            return False
        from server.modules.japanese_lipsync_addon import _manifest
        return _manifest(root / entry['executable'], verify_package=False) is not None
    except (OSError, ValueError, KeyError, TypeError):
        return False


def installed_releases(root, key):
    if not key or not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink()
                   and not p.name.startswith('.') and (p / key / '.ready').is_file()),
                  key=lambda p: (p / key / '.ready').stat().st_mtime_ns, reverse=True)


def remove_obsolete(root, key, current=None):
    if not root.is_dir():
        return
    for release in root.iterdir():
        if not release.is_dir() or release.is_symlink() or release.name.startswith('.'):
            continue
        target = release / key
        if target == current:
            continue
        if target.is_symlink():
            raise RuntimeError('Unsafe Rhubarb runtime path')
        if not target.is_dir():
            continue
        shutil.rmtree(target)
        if not any(release.iterdir()):
            release.rmdir()


def replace_runtime(staging, target):
    if target.is_symlink():
        raise RuntimeError('Unsafe Rhubarb runtime path')
    backup = target.with_name('.' + target.name + '-' + uuid.uuid4().hex + '.previous')
    if target.exists():
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except OSError:
        if backup.exists():
            os.replace(backup, target)
        raise
    shutil.rmtree(backup, ignore_errors=True)

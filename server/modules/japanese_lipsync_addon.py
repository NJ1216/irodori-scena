"""Optional addon boundary: Rhubarb LAB survives Japanese refinement failures."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path

from server.registry import deps

LOGGER = logging.getLogger(__name__)
LABELS = frozenset(('a', 'i', 'u', 'e', 'o', 'N', 'pau'))
IDENTITY_FIELDS = ('analysisVersion', 'modelSha256', 'processorSha256', 'textInfluence')


def verify_assets(root, files):
    """Check packaged assets once at the export boundary, before cache lookup."""
    if not isinstance(files, dict) or not files:
        raise ValueError('Missing addon asset identities')
    for name, expected in files.items():
        relative = Path(name)
        path = (root / relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root.resolve()):
            raise ValueError('Unsafe addon asset path')
        if not path.is_file():
            raise ValueError('Missing addon asset')
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('Addon asset hash mismatch')


def validate_rows(raw, duration):
    if not isinstance(raw, list) or not raw:
        raise ValueError('Missing LAB rows')
    cursor, rows = 0, []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 3:
            raise ValueError('Invalid LAB row')
        start, end, label = item
        if (type(start) is not int or type(end) is not int or start != cursor
                or end <= start or not isinstance(label, str) or label not in LABELS):
            raise ValueError('Invalid LAB interval')
        rows.append((start, end, label))
        cursor = end
    if cursor != round(duration * 1e7):
        raise ValueError('LAB does not cover the WAV')
    return rows


def _manifest(executable, *, verify_package=True):
    root = executable.parent / 'japanese-lipsync'
    path = root / 'manifest.json'
    if not path.is_file():
        return None
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if not manifest.get('enabled', False):
        return None
    if (manifest.get('schemaVersion') != 1 or manifest.get('textInfluence') != 'none'
            or not isinstance(manifest.get('analysisVersion'), str)):
        raise ValueError('Unsupported Japanese addon manifest')
    keys = ('modelSha256', 'processorSha256', 'executableSha256')
    if 'executionSha256' in manifest:
        keys += ('executionSha256',)
    for key in keys:
        value = manifest.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('Missing addon identity')
    relative = Path(manifest['executable'])
    worker = (root / relative).resolve()
    if relative.is_absolute() or '..' in relative.parts or not worker.is_relative_to(root.resolve()):
        raise ValueError('Unsafe addon executable path')
    if not worker.is_file() or hashlib.sha256(worker.read_bytes()).hexdigest() != manifest['executableSha256']:
        raise ValueError('Japanese addon executable hash mismatch')
    if verify_package and 'files' in manifest:
        verify_assets(root, manifest['files'])
    return manifest, worker, hashlib.sha256(raw).hexdigest()


def _response(payload, manifest, wav_sha, duration):
    if (not isinstance(payload, dict) or payload.get('schemaVersion') != 1
            or payload.get('wavSha256') != wav_sha
            or any(payload.get(k) != manifest[k] for k in IDENTITY_FIELDS)):
        raise ValueError('Addon response identity mismatch')
    if 'executionSha256' in manifest and payload.get('executionSha256') != manifest['executionSha256']:
        raise ValueError('Addon execution identity mismatch')
    return validate_rows(payload.get('rows'), duration)


def refine_with_addon(wav, rows, wav_sha, duration, rhubarb, release_id, cache_root,
                      should_cancel, run_process, cache_lock, *, loaded_addon=None):
    if should_cancel():
        raise deps.GenerationCancelled('エクスポートをキャンセルしました。')
    try:
        loaded = loaded_addon if loaded_addon is not None else _manifest(rhubarb)
        if loaded is None:
            return rows
        manifest, worker, identity = loaded
        baseline_sha = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        key = hashlib.sha256(f'{release_id}:{identity}:{wav_sha}:{baseline_sha}'.encode()).hexdigest()
        cache = cache_root / 'japanese' / (key + '.json')
        lock = cache_lock('japanese:' + key, should_cancel)
        try:
            return _refine(wav, rows, wav_sha, duration, manifest, worker, cache, should_cancel, run_process)
        finally:
            lock.release()
    except deps.GenerationCancelled:
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
        LOGGER.warning('Japanese lip-sync addon failed; retaining Rhubarb LAB (%s)', type(error).__name__)
        return rows


def _refine(wav, rows, wav_sha, duration, manifest, worker, cache, should_cancel, run_process):
    if cache.is_file():
        try:
            return _response(json.loads(cache.read_text(encoding='utf-8')), manifest, wav_sha, duration)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    with tempfile.TemporaryDirectory(prefix='scena-japanese-lipsync-') as temporary:
        request, output = Path(temporary) / 'request.json', Path(temporary) / 'result.json'
        request.write_text(json.dumps({'schemaVersion': 1, 'wavPath': str(wav), 'wavSha256': wav_sha,
                                       'rows': rows}, ensure_ascii=False), encoding='utf-8')
        run_process([str(worker), '--input', str(request), '--output', str(output)], worker.parent,
                    min(600.0, max(30.0, duration * 4)), should_cancel)
        payload = json.loads(output.read_text(encoding='utf-8'))
        candidate = _response(payload, manifest, wav_sha, duration)
    if should_cancel():
        raise deps.GenerationCancelled('エクスポートをキャンセルしました。')
    # Cache only validated successes; a failed addon remains eligible for retry.
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary_cache = cache.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        fields = ('schemaVersion', 'wavSha256', 'rows', *IDENTITY_FIELDS)
        if 'executionSha256' in manifest:
            fields += ('executionSha256',)
        temporary_cache.write_text(json.dumps({k: payload[k] for k in fields}), encoding='utf-8')
        os.replace(temporary_cache, cache)
    finally:
        temporary_cache.unlink(missing_ok=True)
    return candidate

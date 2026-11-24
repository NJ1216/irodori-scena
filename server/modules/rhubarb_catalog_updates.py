"""Fetch the publisher's package hashes, retaining verified metadata when offline."""
import json
import hashlib
import re
import threading
import time
import urllib.request
from pathlib import PurePosixPath

PUBLISHER = 'https://github.com/NJ1216/irodori-scena/releases/'
CATALOG_URL = PUBLISHER + 'download/rhubarb-addon/rhubarb-runtime-updates.json'
LOCK = threading.Lock()
LAST_CHECK = {}
HASH = re.compile(r'^[0-9a-f]{64}$')


def validate_catalog(catalog):
    if catalog.get('schemaVersion') != 1 or not re.fullmatch(r'[A-Za-z0-9._-]+', catalog['releaseId']):
        raise ValueError('Unsupported runtime catalogue')
    if catalog['releaseId'] in ('.', '..') or not catalog['releaseUrl'].startswith(PUBLISHER + 'tag/'):
        raise ValueError('Unexpected runtime publisher')
    for key, entry in catalog['platforms'].items():
        if key not in ('darwin-arm64', 'windows-x64'):
            raise ValueError('Unsupported runtime platform')
        if not entry.get('available'):
            continue
        if not entry['url'].startswith(PUBLISHER + 'download/'):
            raise ValueError('Unexpected package publisher')
        if not all(HASH.fullmatch(entry[field]) for field in ('archiveSha256', 'executableSha256')):
            raise ValueError('Missing package hashes')
        files = entry['files']
        if not isinstance(files, list) or not files or len(files) > 5000 or len(files) != len(set(files)):
            raise ValueError('Invalid runtime file inventory')
        for name in [entry['executable'], *files]:
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or not name.startswith('rhubarb/'):
                raise ValueError('Unsafe runtime path')
        if entry['executable'] not in files:
            raise ValueError('Missing runtime executable')
        if entry.get('japaneseAddon') and not HASH.fullmatch(entry['japaneseAddon']['manifestSha256']):
            raise ValueError('Missing addon manifest hash')
    return catalog


def updated_catalog(builtin, root, *, refresh=False):
    cache = root / 'publisher-catalog.json'
    baseline_sha = hashlib.sha256(json.dumps(builtin, sort_keys=True).encode()).hexdigest()
    with LOCK:
        catalog = builtin
        try:
            stored = json.loads(cache.read_text(encoding='utf-8'))
            if stored['baselineSha256'] == baseline_sha:
                catalog = validate_catalog(stored['catalog'])
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        if not refresh or time.monotonic() - LAST_CHECK.get(str(root), -600) < 600:
            return catalog
        LAST_CHECK[str(root)] = time.monotonic()
        try:
            with urllib.request.urlopen(CATALOG_URL, timeout=3) as response:
                raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('Runtime catalogue is too large')
            candidate = validate_catalog(json.loads(raw))
            root.mkdir(parents=True, exist_ok=True)
            pending = cache.with_suffix('.pending')
            pending.write_text(json.dumps({'baselineSha256': baseline_sha, 'catalog': candidate}), encoding='utf-8')
            pending.replace(cache)
            return candidate
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return catalog

"""Hash-based upgrades replace managed runtimes only after successful verification."""
import scena_test_isolation  # noqa: F401
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules.rhubarb_inventory import package_matches, remove_obsolete, replace_runtime
from server.modules.rhubarb_runtime import rhubarb_status, rhubarb_executable


class RhubarbUpdateTests(unittest.TestCase):
    def test_old_installed_release_is_reported_as_an_available_update(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / 'old/darwin-arm64'
            old.mkdir(parents=True)
            (old / '.ready').write_text('{}')
            catalog = {'releaseId': 'new', 'version': '1.14.0', 'license': 'MIT',
                       'sourceUrl': 'source', 'releaseUrl': 'release'}
            entry = {'available': True, 'archiveSha256': 'a' * 64, 'files': ['rhubarb/rhubarb']}
            with patch('server.modules.rhubarb_runtime._entry', return_value=(catalog, 'darwin-arm64', entry)), \
                    patch('server.modules.constants.RHUBARB_RUNTIMES_ROOT', root), \
                    patch('server.modules.rhubarb_runtime._installed_runtime', return_value=(None, None)):
                status = rhubarb_status()
            self.assertTrue(status['installed'])
            self.assertTrue(status['updateAvailable'])
            self.assertFalse(status['ready'])
            self.assertEqual(status['installedReleaseId'], 'old')

    def test_new_catalog_and_failed_or_cancelled_update_keep_old_executable_usable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = root / 'old/darwin-arm64'
            executable = old / 'rhubarb/rhubarb'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'verified old binary')
            old_entry = {'executable': 'rhubarb/rhubarb',
                         'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
            (old / '.ready').write_text(json.dumps({'entry': old_entry}))
            catalog = {'releaseId': 'new', 'version': '1.14.0-scena.2', 'license': 'MIT',
                       'sourceUrl': 'source', 'releaseUrl': 'release'}
            entry = {**old_entry, 'available': True, 'archiveSha256': 'a' * 64,
                     'files': ['rhubarb/rhubarb']}
            for state in ('failed', 'cancelled'):
                with self.subTest(state=state), \
                        patch('server.modules.rhubarb_runtime._entry', return_value=(catalog, 'darwin-arm64', entry)), \
                        patch('server.modules.constants.RHUBARB_RUNTIMES_ROOT', root), \
                        patch('server.modules.rhubarb_runtime.INSTALL_JOB', {'state': state}), \
                        patch('server.modules.rhubarb_runtime.installed_addon_status', return_value=None):
                    self.assertEqual(rhubarb_executable().read_bytes(), b'verified old binary')
                    status = rhubarb_status()
                    self.assertTrue(status['ready'])
                    self.assertTrue(status['updateAvailable'])
                    self.assertEqual(status['installedReleaseId'], 'old')

    def test_legacy_marker_uses_shipped_history_when_builtin_advances(self):
        from server.modules.rhubarb_runtime import _installed_runtime
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalogs = root / 'catalogs'
            catalogs.mkdir()
            new = {'releaseId': 'new', 'platforms': {}}
            (catalogs / 'rhubarb-runtime.json').write_text(json.dumps(new))
            old = root / 'runtimes/old/darwin-arm64'
            executable = old / 'rhubarb/rhubarb'
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b'old executable')
            (old / '.ready').write_text('{}')
            entry = {'executable': 'rhubarb/rhubarb',
                     'executableSha256': hashlib.sha256(executable.read_bytes()).hexdigest()}
            (catalogs / 'rhubarb-runtime-old.json').write_text(json.dumps(
                {'releaseId': 'old', 'platforms': {'darwin-arm64': entry}}))
            with patch('server.modules.rhubarb_runtime.CATALOG_PATH', catalogs / 'rhubarb-runtime.json'), \
                    patch('server.modules.constants.RHUBARB_RUNTIMES_ROOT', root / 'runtimes'):
                self.assertEqual(_installed_runtime(new, 'darwin-arm64', entry), (executable, old))

    def test_changed_archive_requires_update_even_when_executable_is_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '.ready').write_text(json.dumps({'archiveSha256': 'old'}))
            entry = {'archiveSha256': 'new', 'japaneseAddon': {'manifestSha256': 'new'}}
            self.assertFalse(package_matches(root, entry))

    def test_success_removes_old_version_but_preserves_other_platform(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('old/darwin-arm64', 'old/windows-x64', 'new/darwin-arm64'):
                path = root / name
                path.mkdir(parents=True)
                (path / '.ready').write_text('{}')
            current = root / 'new/darwin-arm64'
            invalid = root / 'invalid/darwin-arm64'
            invalid.mkdir(parents=True)
            remove_obsolete(root, 'darwin-arm64', current)
            self.assertFalse(invalid.exists())
            self.assertFalse((root / 'old/darwin-arm64').exists())
            self.assertTrue((root / 'old/windows-x64').exists())
            self.assertTrue(current.exists())

    def test_failed_atomic_replacement_restores_previous_installation(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target, staging = root / 'target', root / 'staging'
            target.mkdir()
            (target / 'old').write_text('keep')
            staging.mkdir()
            actual_replace = os.replace
            def replace(source, destination):
                if source == staging:
                    raise OSError('cannot promote')
                return actual_replace(source, destination)
            with patch('server.modules.rhubarb_inventory.os.replace', side_effect=replace):
                with self.assertRaises(OSError):
                    replace_runtime(staging, target)
            self.assertEqual((target / 'old').read_text(), 'keep')
            self.assertFalse(list(root.glob('*.previous')))

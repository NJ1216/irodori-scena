"""Package installation fails closed without damaging an existing runtime."""
import scena_test_isolation  # noqa: F401
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from server.modules.japanese_lipsync_install import install_local_addon, verify_packaged_addon


class InstallTests(unittest.TestCase):
    def test_local_install_replaces_only_after_self_test_and_keeps_rhubarb(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / 'worker').write_bytes(b'accepted')
            manifest = {'files': {'worker': hashlib.sha256(b'accepted').hexdigest()}, 'analysisVersion': 'v3'}
            (source / 'manifest.json').write_text(json.dumps(manifest))
            rhubarb = root / 'rhubarb'
            rhubarb.write_bytes(b'rhubarb')
            target = root / 'japanese-lipsync'
            target.mkdir()
            (target / 'previous').write_text('preserved')
            with patch('server.modules.japanese_lipsync_install.verify_packaged_addon', side_effect=ValueError('failed')):
                with self.assertRaises(ValueError):
                    install_local_addon(source, rhubarb, 'darwin-arm64', Mock())
            self.assertEqual((target / 'previous').read_text(), 'preserved')
            self.assertFalse((root / '.japanese-lipsync-install.lock').exists())
            with patch('server.modules.japanese_lipsync_install.verify_packaged_addon', return_value={'ready': True}):
                self.assertEqual(install_local_addon(source, rhubarb, 'darwin-arm64', Mock()), {'ready': True})
            self.assertEqual((target / 'worker').read_bytes(), b'accepted')
            self.assertEqual(rhubarb.read_bytes(), b'rhubarb')
            self.assertFalse((target / 'previous').exists())
            self.assertFalse((root / '.japanese-lipsync-install.lock').exists())

    def test_plain_rhubarb_needs_no_japanese_worker(self):
        self.assertIsNone(verify_packaged_addon(Path('/missing'), {}, 'darwin-arm64', Mock()))

    def test_self_test_identity_and_asset_hashes_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            addon = root / 'japanese-lipsync'
            addon.mkdir()
            worker = addon / 'worker'
            worker.write_bytes(b'worker')
            digest = hashlib.sha256(b'worker').hexdigest()
            manifest = {'schemaVersion': 1, 'enabled': True, 'analysisVersion': 'v3',
                        'textInfluence': 'none', 'modelSha256': 'a' * 64, 'processorSha256': 'b' * 64,
                        'executionSha256': 'c' * 64, 'executable': 'worker', 'executableSha256': digest,
                        'files': {'worker': digest}}
            path = addon / 'manifest.json'
            path.write_text(json.dumps(manifest), encoding='utf-8')
            entry = {'japaneseAddon': {'manifestSha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                      'analysisVersion': 'v3', 'license': 'Apache-2.0'}}
            architecture = Mock()
            response = Mock(stdout=json.dumps(manifest))
            with patch('server.modules.japanese_lipsync_install.subprocess.run', return_value=response):
                result = verify_packaged_addon(root / 'rhubarb', entry, 'darwin-arm64', architecture)
                self.assertEqual(result['analysisVersion'], 'v3')
                architecture.assert_called_once_with(worker.resolve(), 'darwin-arm64')
                response.stdout = json.dumps({**manifest, 'executionSha256': 'd' * 64})
                with self.assertRaisesRegex(ValueError, 'self-test identity'):
                    verify_packaged_addon(root / 'rhubarb', entry, 'darwin-arm64', architecture)
            worker.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                verify_packaged_addon(root / 'rhubarb', entry, 'darwin-arm64', architecture)

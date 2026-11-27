"""Publisher metadata is bounded, cached, safe, and optional while offline."""
import scena_test_isolation  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from server.modules.rhubarb_catalog_updates import LAST_CHECK, updated_catalog, validate_catalog


def catalog():
    return {'schemaVersion': 1, 'releaseId': '1.14.0-scena.1',
            'releaseUrl': 'https://github.com/NJ1216/irodori-scena/releases/tag/release',
            'platforms': {'darwin-arm64': {'available': True, 'archiveSha256': 'a' * 64,
                'executableSha256': 'b' * 64, 'executable': 'rhubarb/rhubarb',
                'files': ['rhubarb/rhubarb'],
                'url': 'https://github.com/NJ1216/irodori-scena/releases/download/release/addon.zip'}}}


class CatalogUpdateTests(unittest.TestCase):
    def test_rejects_foreign_publisher_unsafe_inventory_and_bad_hash(self):
        for field, value in [('url', 'https://other.example/addon.zip'),
                             ('files', ['rhubarb/../../outside']), ('archiveSha256', 'wrong')]:
            candidate = catalog()
            candidate['platforms']['darwin-arm64'][field] = value
            with self.assertRaises(ValueError):
                validate_catalog(candidate)

    def test_caches_checked_metadata_and_retains_it_while_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            builtin, candidate = catalog(), catalog()
            candidate['platforms']['darwin-arm64']['archiveSha256'] = 'c' * 64
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(candidate).encode()
            with patch('server.modules.rhubarb_catalog_updates.urllib.request.urlopen', return_value=response) as fetch:
                self.assertEqual(updated_catalog(builtin, root, refresh=True), candidate)
                self.assertEqual(updated_catalog(builtin, root, refresh=True), candidate)
                fetch.assert_called_once()
            LAST_CHECK.clear()
            with patch('server.modules.rhubarb_catalog_updates.urllib.request.urlopen', side_effect=OSError('offline')):
                self.assertEqual(updated_catalog(builtin, root, refresh=True), candidate)
                newer_builtin = catalog()
                newer_builtin['platforms']['darwin-arm64']['archiveSha256'] = 'd' * 64
                self.assertEqual(updated_catalog(newer_builtin, root), newer_builtin)

    def test_invalid_remote_metadata_does_not_replace_builtin(self):
        with tempfile.TemporaryDirectory() as temporary:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{}'
            with patch('server.modules.rhubarb_catalog_updates.urllib.request.urlopen', return_value=response):
                self.assertEqual(updated_catalog(catalog(), Path(temporary), refresh=True), catalog())

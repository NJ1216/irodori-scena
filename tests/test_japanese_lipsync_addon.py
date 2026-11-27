"""Optional refinement identity, failure fallback, cancellation and cache contracts."""
import scena_test_isolation  # noqa: F401
import hashlib
import json
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import server.app  # noqa: F401
from server.modules.japanese_lipsync_addon import refine_with_addon, validate_rows
from server.modules.rhubarb_lipsync import _cache_lock


class JapaneseAddonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.rhubarb = self.root / 'rhubarb'
        self.rhubarb.write_bytes(b'rhubarb')
        self.addon = self.root / 'japanese-lipsync'
        self.addon.mkdir()
        self.worker = self.addon / 'worker'
        self.worker.write_bytes(b'worker')
        self.manifest = {'schemaVersion': 1, 'enabled': True, 'analysisVersion': 'v2',
                         'textInfluence': 'none', 'modelSha256': 'a' * 64,
                         'processorSha256': 'b' * 64, 'executable': 'worker',
                         'executableSha256': hashlib.sha256(b'worker').hexdigest()}
        self.write_manifest()
        self.rows = [(0, 10_000_000, 'i')]
        self.calls = 0
        self.cancel = False

    def write_manifest(self):
        (self.addon / 'manifest.json').write_text(json.dumps(self.manifest))

    def run_worker(self, command, *_):
        self.calls += 1
        payload = {**self.manifest, 'wavSha256': 'c' * 64, 'rows': [[0, 10_000_000, 'e']]}
        Path(command[command.index('--output') + 1]).write_text(json.dumps(payload))

    def refine(self, run=None):
        return refine_with_addon(self.root / 'audio.wav', self.rows, 'c' * 64, 1,
                                 self.rhubarb, 'release', self.root / 'cache', lambda: self.cancel,
                                 run or self.run_worker, _cache_lock)

    def test_success_cache_and_analysis_model_processor_invalidation(self):
        self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])
        self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])
        self.assertEqual(self.calls, 1)
        for key, value in (('analysisVersion', 'v3'), ('modelSha256', 'd' * 64),
                           ('processorSha256', 'e' * 64)):
            self.manifest[key] = value
            self.write_manifest()
            self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])
        self.assertEqual(self.calls, 4)

    def test_modified_packaged_asset_cannot_reuse_validated_lab_cache(self):
        asset = self.addon / 'config.json'
        asset.write_bytes(b'accepted')
        self.manifest['files'] = {'config.json': hashlib.sha256(b'accepted').hexdigest()}
        self.write_manifest()
        self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])
        asset.write_bytes(b'changed')
        with self.assertLogs('server.modules.japanese_lipsync_addon', level='WARNING'):
            self.assertEqual(self.refine(), self.rows)
        self.assertEqual(self.calls, 1)

    def test_packaged_asset_cannot_escape_addon_root(self):
        self.manifest['files'] = {'../rhubarb': hashlib.sha256(b'rhubarb').hexdigest()}
        self.write_manifest()
        with self.assertLogs('server.modules.japanese_lipsync_addon', level='WARNING'):
            self.assertEqual(self.refine(), self.rows)
        self.assertEqual(self.calls, 0)

    def test_failed_or_malformed_worker_does_not_poison_success_cache(self):
        for response in ({}, {'schemaVersion': 1, 'wavSha256': 'wrong'},
                         {**self.manifest, 'wavSha256': 'c' * 64, 'rows': [[0, 100, 'e']]}):
            def bad(command, *_):
                Path(command[command.index('--output') + 1]).write_text(json.dumps(response))
            with self.assertLogs('server.modules.japanese_lipsync_addon', level='WARNING'):
                self.assertEqual(self.refine(bad), self.rows)
        with self.assertLogs('server.modules.japanese_lipsync_addon', level='WARNING'):
            self.assertEqual(self.refine(Mock(side_effect=RuntimeError('crash'))), self.rows)
        self.assertFalse((self.root / 'cache').exists())
        self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])

    def test_execution_identity_is_checked_and_invalidates_success_cache(self):
        self.manifest['executionSha256'] = 'f' * 64
        self.write_manifest()
        self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])
        self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])
        self.assertEqual(self.calls, 1)
        self.manifest['executionSha256'] = '0' * 64
        self.write_manifest()
        def stale(command, *_):
            payload = {**self.manifest, 'executionSha256': 'f' * 64,
                       'wavSha256': 'c' * 64, 'rows': [[0, 10_000_000, 'e']]}
            Path(command[command.index('--output') + 1]).write_text(json.dumps(payload))
        with self.assertLogs('server.modules.japanese_lipsync_addon', level='WARNING'):
            self.assertEqual(self.refine(stale), self.rows)
        self.assertEqual(self.refine(), [(0, 10_000_000, 'e')])
        self.assertEqual(self.calls, 2)

    def test_missing_disabled_corrupt_or_escaping_addon_keeps_rhubarb(self):
        (self.addon / 'manifest.json').unlink()
        self.assertEqual(self.refine(), self.rows)
        self.manifest['enabled'] = False
        self.write_manifest()
        self.assertEqual(self.refine(), self.rows)
        self.manifest['enabled'] = True
        for path in ('../rhubarb', str(self.rhubarb)):
            self.manifest['executable'] = path
            self.write_manifest()
            with self.assertLogs('server.modules.japanese_lipsync_addon', level='WARNING'):
                self.assertEqual(self.refine(), self.rows)
        self.manifest['executable'] = 'worker'
        self.write_manifest()
        self.worker.write_bytes(b'corrupt')
        with self.assertLogs('server.modules.japanese_lipsync_addon', level='WARNING'):
            self.assertEqual(self.refine(), self.rows)
        self.assertEqual(self.calls, 0)

    def test_cancel_is_not_converted_to_fallback_or_cached(self):
        self.cancel = True
        with self.assertRaises(server.app.GenerationCancelled):
            self.refine()
        self.cancel = False

        def cancelled(*_):
            raise server.app.GenerationCancelled('cancel')
        with self.assertRaises(server.app.GenerationCancelled):
            self.refine(cancelled)
        self.assertFalse((self.root / 'cache').exists())

    def test_rows_reject_gaps_boolean_times_invalid_labels_and_end_mismatch(self):
        for rows in ([], [[1, 10_000_000, 'e']], [[False, 10_000_000, 'e']],
                     [[0, 10_000_000, 'bad']], [[0, 100, 'e']]):
            with self.assertRaises(ValueError):
                validate_rows(rows, 1)

    def test_identical_concurrent_requests_share_one_refinement(self):
        entered, release = threading.Event(), threading.Event()

        def slow_worker(command, *args):
            entered.set()
            release.wait(timeout=2)
            self.run_worker(command, *args)

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.refine, slow_worker)
            self.assertTrue(entered.wait(timeout=2))
            second = executor.submit(self.refine, slow_worker)
            release.set()
            self.assertEqual(first.result(timeout=2), second.result(timeout=2))
        self.assertEqual(self.calls, 1)


if __name__ == '__main__':
    unittest.main()

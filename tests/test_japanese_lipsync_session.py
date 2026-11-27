"""A job-owned worker shares startup, preserves replies and stops on every exit."""
import scena_test_isolation  # noqa: F401
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from contextlib import contextmanager

import server.app  # noqa: F401
from server.modules.japanese_lipsync_session import AddonSession
from server.modules.export_bundle import ExportLine, _write_labs

WORKER = '''
import argparse,json,time,os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--serve',action='store_true');p.add_argument('--directory');a=p.parse_args()
d=Path(a.directory)
identity=json.loads((Path(__file__).parent/'identity.json').read_text())
def publish(path,payload):
 t=path.with_suffix('.pending');t.write_text(json.dumps(payload));t.replace(path)
publish(d/'ready.json',identity)
while not (d/'stop').exists():
 for request in d.glob('*.request.json'):
  payload=json.loads(request.read_text())
  if payload.get('crash'):os._exit(7)
  if payload.get('stall'):
   while True:time.sleep(.1)
  result={'error':'row_failure'} if payload.get('fail') else {**identity,**payload}
  publish(d/request.name.replace('.request.json','.result.json'),result)
  request.unlink()
 time.sleep(.01)
'''


class JapaneseSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = {'analysisVersion': 'v2', 'modelSha256': 'a' * 64,
                         'processorSha256': 'b' * 64, 'textInfluence': 'none'}
        script = self.root / 'worker.py'
        script.write_text(WORKER)
        (self.root / 'identity.json').write_text(json.dumps(self.identity))
        self.session = AddonSession([sys.executable, str(script)], self.identity)
        self.addCleanup(self.session.close)

    def run_request(self, name, payload, cancel=lambda: False, timeout=5):
        request, output = self.root / (name + '.json'), self.root / (name + '-out.json')
        request.write_text(json.dumps(payload))
        self.session.run(['worker', '--input', str(request), '--output', str(output)],
                         self.root, timeout, cancel)
        return json.loads(output.read_text())

    def test_parallel_requests_share_process_and_responses_remain_owned(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(self.run_request, 'a', {'wavSha256': 'a'})
            second = executor.submit(self.run_request, 'b', {'wavSha256': 'b'})
            self.assertEqual(first.result()['wavSha256'], 'a')
            self.assertEqual(second.result()['wavSha256'], 'b')
        pid = self.session.process.pid
        self.assertEqual(self.run_request('c', {'wavSha256': 'c'})['wavSha256'], 'c')
        self.assertEqual(self.session.process.pid, pid)
        process, directory = self.session.process, self.session.directory
        self.session.close()
        self.assertIsNotNone(process.poll())
        self.assertFalse(directory.exists())

    def test_row_failure_keeps_worker_and_next_sibling(self):
        self.assertEqual(self.run_request('bad', {'fail': True}), {'error': 'row_failure'})
        self.assertEqual(self.run_request('good', {'wavSha256': 'good'})['wavSha256'], 'good')

    def test_execution_mismatch_closes_worker(self):
        self.identity['executionSha256'] = 'f' * 64
        with self.assertRaisesRegex(RuntimeError, 'execution identity mismatch'):
            self.run_request('mismatch', {})
        self.assertTrue(self.session.closed)
        self.assertIsNotNone(self.session.process.poll())
        self.assertFalse(self.session.directory.exists())

    def test_crash_closes_session_without_restart(self):
        with self.assertRaises(RuntimeError):
            self.run_request('crash', {'crash': True})
        process = self.session.process
        with self.assertRaises(RuntimeError):
            self.run_request('after', {})
        self.assertIs(self.session.process, process)
        self.assertFalse(self.session.directory.exists())

    def test_cancel_and_timeout_stop_owned_process(self):
        def cancel():
            return bool(self.session.process and (self.session.directory / 'ready.json').is_file())
        with self.assertRaises(server.app.GenerationCancelled):
            self.run_request('cancel', {}, cancel=cancel)
        self.assertIsNotNone(self.session.process.poll())
        session = AddonSession([sys.executable, str(self.root / 'worker.py')], self.identity)
        self.addCleanup(session.close)
        self.session = session
        with self.assertRaises(RuntimeError):
            self.run_request('stall', {'stall': True}, timeout=.5)
        self.assertIsNotNone(session.process.poll())

    def test_identity_mismatch_is_not_accepted(self):
        self.session.manifest = {**self.identity, 'modelSha256': 'wrong'}
        with self.assertRaises(RuntimeError):
            self.run_request('wrong', {})
        self.assertTrue(self.session.closed)

    def test_export_passes_session_and_releases_it_when_lab_fails(self):
        closed = []
        received = []

        @contextmanager
        def scoped_session():
            try:
                yield self.session
            finally:
                closed.append(True)
                self.session.close()

        def generate(_wav, _cancel, _threads, *, addon_session):
            received.append(addon_session)
            raise RuntimeError('one line failed')

        item = ExportLine(1, {}, {'id': 'line'}, 'cast', 'text', '001')
        with patch('server.modules.japanese_lipsync_session.export_addon_session', scoped_session), patch(
            'server.modules.rhubarb_lipsync.generate_rhubarb_lab', side_effect=generate
        ), patch('server.modules.export_service.update_export_job'):
            count, failures = _write_labs([(item, self.root / 'audio.wav', self.root / 'out.lab')], 'job')
        self.assertEqual(received, [self.session])
        self.assertEqual(count, 0)
        self.assertEqual(len(failures), 1)
        self.assertEqual(closed, [True])
        self.assertFalse(self.session.directory.exists())


if __name__ == '__main__':
    unittest.main()

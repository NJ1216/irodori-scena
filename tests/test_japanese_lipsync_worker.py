"""The file worker reuses per-thread models and retains successful sibling replies."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from japanese_lipsync_worker import atomic_json, execution_identity, process, serve, serve_request
from lipsync_model_profile import COMMON_ANALYSIS_VERSION, COMMON_MODEL_SHA256, V3_MODEL_SHA256


class WorkerPoolTests(unittest.TestCase):
    def test_confirmation_and_cache_version_apply_only_to_new_model(self):
        import hashlib
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            wav = Path(temporary) / 'audio.wav'
            wav.write_bytes(b'fixture')
            request = {'wavPath': str(wav), 'wavSha256': hashlib.sha256(b'fixture').hexdigest(),
                       'rows': [[0, 10_000_000, 'i']]}
            for model, enabled, version in ((V3_MODEL_SHA256, False, 'japanese-ctc-context-v3'),
                                            (COMMON_MODEL_SHA256, True, COMMON_ANALYSIS_VERSION)):
                def recognize(*_):
                    return [], []
                recognize.model_sha256 = model
                with patch('japanese_lipsync_worker.read_wav', return_value=(np.zeros(16000), 16000)), \
                        patch('japanese_lipsync_worker.refine_japanese',
                              return_value=(request['rows'], {})) as refine:
                    result = process(request, recognize)
                self.assertEqual(result['analysisVersion'], version)
                self.assertEqual(refine.call_args.kwargs['confirm_vowels'], enabled)

    def test_mac_execution_identity_preserves_completed_worker_settings(self):
        import hashlib
        expected = {'runtime': 'onnxruntime', 'runtimeVersion': '1.20.1', 'provider': 'CPUExecutionProvider',
                    'intraThreads': 2, 'interThreads': 1, 'spinning': True,
                    'preprocessing': 'resample-normalize-float32-v1', 'mode': 'baseline'}
        with patch('japanese_lipsync_worker.sys.platform', 'darwin'), \
                patch('japanese_lipsync_worker.ort.__version__', '1.20.1'):
            settings, digest = execution_identity()
        self.assertEqual(settings, expected)
        self.assertEqual(digest, hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest())

    def test_windows_runtime_hash_is_in_response_and_cache_execution_identity(self):
        with patch('japanese_lipsync_worker.sys.platform', 'win32'), \
                patch('lipsync_runtime_identity.windows_runtime_identity',
                      side_effect=[{'runtimeBuild': 'patch-v1', 'runtimeBinarySha256': 'one'},
                                   {'runtimeBuild': 'patch-v1', 'runtimeBinarySha256': 'two'}]):
            first, second = execution_identity(), execution_identity()
        self.assertEqual(first[0]['runtimeBuild'], 'patch-v1')
        self.assertEqual(first[0]['runtimeBinarySha256'], 'one')
        self.assertNotEqual(first[1], second[1])

    def test_non_ascii_destination_survives_legacy_windows_text_codepage(self):
        class LegacyLocalePath(type(Path())):
            def read_text(self, encoding=None, **kwargs):
                return super().read_text(encoding=encoding or 'cp1252', **kwargs)
            def write_text(self, text, encoding=None, **kwargs):
                return super().write_text(text, encoding=encoding or 'cp1252', **kwargs)
        with tempfile.TemporaryDirectory() as temporary:
            request = LegacyLocalePath(temporary) / 'line.request.json'
            request.write_bytes(json.dumps({'wavPath': '葵の声.wav'}, ensure_ascii=False).encode('utf-8'))
            with patch('japanese_lipsync_worker.process', side_effect=lambda payload, _: payload):
                serve_request(request, None, 'processor')
            result = request.parent / 'line.result.json'
            self.assertEqual(json.loads(result.read_text(encoding='utf-8'))['wavPath'], '葵の声.wav')
            self.assertFalse(request.exists())

    def test_normal_response_is_small_and_diagnostic_audit_is_opt_in(self):
        import hashlib
        import numpy as np
        with tempfile.TemporaryDirectory() as temporary:
            wav = Path(temporary) / 'audio.wav'
            wav.write_bytes(b'fixture')
            request = {'wavPath': str(wav), 'wavSha256': hashlib.sha256(b'fixture').hexdigest(),
                       'rows': [[0, 10_000_000, 'i']]}
            with patch('japanese_lipsync_worker.read_wav', return_value=(np.zeros(16000), 16000)), \
                    patch('japanese_lipsync_worker.refine_japanese', return_value=(request['rows'], {'local': [1]})):
                self.assertNotIn('audit', process(request, lambda *_: ([], [])))
                request['diagnostics'] = True
                self.assertEqual(process(request, lambda *_: ([], []))['audit'], {'local': [1]})

    def test_models_load_once_per_slot_and_failed_row_does_not_drop_siblings(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            barrier = threading.Barrier(4)
            models, lock = [], threading.Lock()

            def factory():
                with lock:
                    models.append(threading.get_ident())
                return lambda *_: ([], [])

            def process(request, recognize):
                recognize(None, 1)
                if request['id'] < 4:
                    barrier.wait(timeout=3)
                if request.get('fail'):
                    raise ValueError('one row')
                return {'id': request['id']}

            def await_results(count):
                deadline = time.monotonic() + 5
                while len(list(directory.glob('*.result.json'))) < count:
                    if time.monotonic() > deadline:
                        self.fail('Missing independent replies')
                    time.sleep(.01)

            with patch('japanese_lipsync_worker.process', side_effect=process):
                thread = threading.Thread(target=serve, args=(directory, None, 'processor'),
                                          kwargs={'recognizer_factory': factory})
                thread.start()
                try:
                    for i in range(4):
                        atomic_json(directory / f'{i}.request.json', {'id': i})
                    await_results(4)
                    for i in range(4, 8):
                        atomic_json(directory / f'{i}.request.json', {'id': i, 'fail': i == 5})
                    await_results(8)
                    self.assertEqual(len(models), 4)
                    self.assertEqual(len(set(models)), 4)
                    self.assertEqual(json.loads((directory / '5.result.json').read_text()), {'error': 'ValueError'})
                    self.assertEqual(json.loads((directory / '7.result.json').read_text())['id'], 7)
                finally:
                    (directory / 'stop').touch()
                    thread.join(timeout=5)
                self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()

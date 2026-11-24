"""Prevent the reproduced Windows bytecode-analysis failure before packaging."""
import unittest
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from tools.release.build_japanese_lipsync import packaged_execution, profile_build_args, verify_build_python


class JapaneseWorkerBuildTests(unittest.TestCase):
    def test_windows_rejects_the_interpreter_that_failed_native_modulegraph(self):
        with self.assertRaisesRegex(ValueError, 'Python 3.12.13'):
            verify_build_python('win32', (3, 13, 12))

    def test_windows_accepts_pinned_worker_python_and_mac_keeps_existing_python(self):
        verify_build_python('win32', (3, 12, 13))
        verify_build_python('darwin', (3, 13, 12))

    def test_new_worker_packages_versions_required_by_native_self_test(self):
        self.assertEqual(profile_build_args('common-v4'),
                         ['--copy-metadata', 'onnxruntime', '--copy-metadata', 'numpy', '--copy-metadata', 'scipy',
                          '--exclude-module', 'setuptools', '--exclude-module', 'pkg_resources'])
        self.assertEqual(profile_build_args('v3'), [])
        with self.assertRaises(ValueError):
            profile_build_args('unknown')

    def test_manifest_uses_packaged_library_identity_and_rejects_false_probe_hash(self):
        execution = {'modelExecutionProfile': 'new', 'runtimeBinarySha256': 'packaged-bytes'}
        digest = hashlib.sha256(json.dumps(execution, sort_keys=True).encode()).hexdigest()
        identity = {'files': {'model_quantized.onnx': 'model'}, 'executionProfile': 'new'}
        probe = {'modelSha256': 'model', 'execution': execution, 'executionSha256': digest}
        with patch('tools.release.build_japanese_lipsync.subprocess.check_output',
                   return_value=json.dumps(probe).encode()):
            self.assertEqual(packaged_execution(Path('worker'), identity), (execution, digest))
        probe['executionSha256'] = 'source-bytes'
        with patch('tools.release.build_japanese_lipsync.subprocess.check_output',
                   return_value=json.dumps(probe).encode()), self.assertRaises(ValueError):
            packaged_execution(Path('worker'), identity)

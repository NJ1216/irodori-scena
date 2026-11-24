"""The new profile is closed, pinned and never shares the previous cache identity."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.lipsync_model_profile import COMMON_MODEL_SHA256, DEPENDENCIES, V3_MODEL_SHA256, common_execution


class ModelProfileTests(unittest.TestCase):
    def test_previous_profile_keeps_its_execution_identity_without_library_probes(self):
        self.assertEqual(common_execution(V3_MODEL_SHA256, '/missing', threads=2,
                                          provider='CPUExecutionProvider'), {})

    def test_new_profile_binds_real_binaries_and_rejects_patched_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'capi').mkdir()
            library = root / 'capi' / 'binding.so'
            library.write_bytes(b'first')
            def identity():
                return common_execution(COMMON_MODEL_SHA256, root, threads=2, provider='CPUExecutionProvider')
            with patch('tools.lipsync_model_profile.importlib.metadata.version', side_effect=DEPENDENCIES.__getitem__):
                first = identity()
                library.write_bytes(b'second')
                self.assertNotEqual(first['runtimeBinarySha256'], identity()['runtimeBinarySha256'])
                (root / 'scena-runtime.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'unmodified'):
                    identity()

    def test_new_profile_rejects_dependency_or_cpu_setting_drift(self):
        with patch('tools.lipsync_model_profile.importlib.metadata.version', return_value='changed'):
            with self.assertRaisesRegex(ValueError, 'versions'):
                common_execution(COMMON_MODEL_SHA256, '/missing', threads=2, provider='CPUExecutionProvider')
        for model, threads, provider in ((COMMON_MODEL_SHA256, 1, 'CPUExecutionProvider'),
                                         (COMMON_MODEL_SHA256, 2, 'CUDAExecutionProvider'),
                                         ('unrecognized', 2, 'CPUExecutionProvider')):
            with self.subTest(model=model, threads=threads, provider=provider), self.assertRaises(ValueError):
                common_execution(model, '/missing', threads=threads, provider=provider)

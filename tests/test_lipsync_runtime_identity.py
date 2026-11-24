"""Patched Runtime declarations cannot hide changed CPU binaries or reuse cache identity."""
import json
import tempfile
import unittest
from pathlib import Path

from tools.lipsync_runtime_identity import binary_hashes, windows_runtime_identity


class RuntimeIdentityTests(unittest.TestCase):
    def test_accuracy_setting_is_bound_to_identity_and_unknown_options_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            declaration = self.fixture(root)
            metadata = root / 'scena-runtime.json'
            metadata.write_text(json.dumps(declaration))
            before = windows_runtime_identity(root, '1.20.1')
            declaration['sessionOptions'] = {'session.x64quantprecision': '1'}
            metadata.write_text(json.dumps(declaration))
            after = windows_runtime_identity(root, '1.20.1')
            self.assertEqual(after['runtimeSessionOptions'], declaration['sessionOptions'])
            self.assertNotEqual(before['runtimeMetadataSha256'], after['runtimeMetadataSha256'])
            for options in ({'session.x64quantprecision': '0'}, {'arbitrary.setting': '1'}):
                declaration['sessionOptions'] = options
                metadata.write_text(json.dumps(declaration))
                with self.assertRaisesRegex(ValueError, 'Unsupported Windows Runtime session options'):
                    windows_runtime_identity(root, '1.20.1')

    def fixture(self, root):
        (root / 'capi').mkdir()
        (root / 'capi/onnxruntime_pybind11_state.pyd').write_bytes(b'binding-one')
        (root / 'capi/onnxruntime.dll').write_bytes(b'cpu-one')
        return {'runtimeVersion': '1.20.1', 'binaryFiles': binary_hashes(root),
                'profile': 'verified-experiment', 'sourceCommit': 'source', 'patchedSourceSha256': 'patch'}

    def test_changed_library_alters_standard_identity_and_rejects_patch_declaration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            declaration = self.fixture(root)
            before = windows_runtime_identity(root, '1.20.1')
            (root / 'scena-runtime.json').write_text(json.dumps(declaration))
            patched = windows_runtime_identity(root, '1.20.1')
            self.assertNotEqual(patched['runtimeBuild'], before['runtimeBuild'])
            (root / 'capi/onnxruntime.dll').write_bytes(b'cpu-two')
            with self.assertRaisesRegex(ValueError, 'CPU library bytes'):
                windows_runtime_identity(root, '1.20.1')
            (root / 'scena-runtime.json').unlink()
            after = windows_runtime_identity(root, '1.20.1')
            self.assertNotEqual(before['runtimeBinarySha256'], after['runtimeBinarySha256'])

    def test_declared_version_and_patch_bytes_are_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            declaration = self.fixture(root)
            (root / 'scena-runtime.json').write_text(json.dumps(declaration))
            first = windows_runtime_identity(root, '1.20.1')
            declaration['patchedSourceSha256'] = 'another-patch'
            (root / 'scena-runtime.json').write_text(json.dumps(declaration))
            second = windows_runtime_identity(root, '1.20.1')
            self.assertNotEqual(first['runtimeMetadataSha256'], second['runtimeMetadataSha256'])
            with self.assertRaisesRegex(ValueError, 'CPU library bytes'):
                windows_runtime_identity(root, '1.20.2')


if __name__ == '__main__':
    unittest.main()

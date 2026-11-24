import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server.irodori_host import inference_device


class IrodoriHostTests(unittest.TestCase):
    def test_mac_preserves_mps_without_querying_cuda(self):
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=Mock()))
        with patch("server.irodori_host.sys.platform", "darwin"):
            self.assertEqual(inference_device(torch), "mps")
        torch.cuda.is_available.assert_not_called()

    def test_windows_uses_cuda_when_available_and_cpu_otherwise(self):
        with patch("server.irodori_host.sys.platform", "win32"):
            for available, expected in [(True, "cuda"), (False, "cpu")]:
                torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: available, get_device_capability=lambda _index=0: (8, 9)))
                self.assertEqual(inference_device(torch), expected)

    def test_windows_uses_cpu_on_gpus_without_cu128_kernels(self):
        with patch("server.irodori_host.sys.platform", "win32"):
            for capability, expected in [((6, 1), "cpu"), ((7, 0), "cuda"), ((8, 9), "cuda")]:
                torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True, get_device_capability=lambda _index=0, value=capability: value))
                with self.subTest(capability=capability):
                    self.assertEqual(inference_device(torch), expected)

    def test_cpu_inference_limits_torch_to_the_physical_core_count(self):
        from server.irodori_host import configure_cpu_threads
        for device, value, current, expected in [
            ("cpu", "8", 16, 8),
            ("cpu", "16", 16, None),
            ("cpu", "0", 16, None),
            ("cpu", "eight", 16, None),
            ("cpu", None, 16, None),
            ("cuda", "8", 16, None),
            ("mps", "8", 16, None),
        ]:
            torch = SimpleNamespace(get_num_threads=Mock(return_value=current), set_num_threads=Mock())
            environ = {} if value is None else {"IRODORI_TTS_CPU_THREADS": value}
            with self.subTest(device=device, value=value):
                self.assertEqual(configure_cpu_threads(torch, device, environ), expected)
                if expected is None:
                    torch.set_num_threads.assert_not_called()
                else:
                    torch.set_num_threads.assert_called_once_with(expected)

    def test_windows_registers_only_an_absolute_shared_ffmpeg_directory(self):
        import os
        import tempfile
        from pathlib import Path
        from server.irodori_host import configure_audio_libraries
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            for name in ("avcodec-62.dll", "avformat-62.dll", "avutil-60.dll"):
                (directory / name).touch()
            with patch("server.irodori_host.sys.platform", "win32"), patch.dict(
                os.environ, {"SCENA_FFMPEG_DIR": root, "PATH": "relative"}
            ), patch("server.irodori_host.os.add_dll_directory", create=True) as register:
                handle = register.return_value
                self.assertEqual(configure_audio_libraries(), [handle])
                register.assert_called_once_with(root)

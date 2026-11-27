import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import patch

from server.modules.windows_gpu import _select_nvml_snapshot
from server import app as _app  # noqa: F401
from server.modules import memory_metrics


class WindowsGpuTests(unittest.TestCase):
    def test_selects_busiest_nvml_adapter_and_largest_vram_allocation(self):
        self.assertEqual(_select_nvml_snapshot([(8, 100, 800), (42, 400, 1200)]), (42, (400, 1200)))
        self.assertEqual(_select_nvml_snapshot([(125, 200, 100), (-4, 10, 200)]), (100, (100, 100)))
        self.assertIsNone(_select_nvml_snapshot([(float("nan"), 0, 100), (10, 0, 0)]))

    def test_windows_uses_cached_nvidia_sample_without_ioreg(self):
        targets = []

        class DeferredThread:
            def __init__(self, *, target, **_kwargs):
                targets.append(target)

            def start(self):
                pass

        with patch.object(memory_metrics.sys, "platform", "win32"), patch.object(
            memory_metrics, "_GPU_CACHED_AT", 0
        ), patch.object(memory_metrics, "_GPU_CACHED_VALUE", None), patch(
            "server.modules.windows_gpu.gpu_utilization", return_value=37
        ) as query, patch.object(memory_metrics.threading, "Thread", DeferredThread):
            self.assertIsNone(memory_metrics._gpu_utilization())
            self.assertEqual(len(targets), 1)
            targets[0]()
            self.assertEqual(memory_metrics._gpu_utilization(), 37)
            query.assert_called_once()

    def test_probe_failure_is_unavailable_instead_of_zero(self):
        with patch.object(memory_metrics.sys, "platform", "win32"), patch.object(
            memory_metrics, "_GPU_CACHED_AT", 0
        ), patch.object(memory_metrics, "_GPU_CACHED_VALUE", None), patch(
            "server.modules.windows_gpu.gpu_utilization", side_effect=FileNotFoundError
        ):
            self.assertIsNone(memory_metrics._gpu_utilization())

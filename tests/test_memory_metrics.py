from __future__ import annotations

import os
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import memory_metrics


class MemoryMetricsTests(unittest.TestCase):
    def test_failed_gpu_samples_are_not_cached(self) -> None:
        with (
            patch.object(memory_metrics, "_GPU_CACHED_AT", 10.0),
            patch.object(memory_metrics, "_GPU_CACHED_VALUE", 25.0),
            patch.object(memory_metrics, "_GPU_IN_FLIGHT", True),
            patch.object(memory_metrics, "_measure_gpu_utilization", return_value=None),
            patch.object(memory_metrics, "_GPU_MEMORY_CACHED_AT", 10.0),
            patch.object(memory_metrics, "_GPU_MEMORY_CACHED_VALUE", (20, 80)),
            patch.object(memory_metrics, "_GPU_MEMORY_IN_FLIGHT", True),
            patch("server.modules.windows_gpu.gpu_memory", return_value=None),
        ):
            memory_metrics._refresh_gpu_utilization()
            memory_metrics._refresh_gpu_memory()
            self.assertEqual(memory_metrics._GPU_CACHED_AT, 0.0)
            self.assertEqual(memory_metrics._GPU_MEMORY_CACHED_AT, 0.0)

    def test_gpu_utilization_refreshes_after_one_second(self) -> None:
        targets = []

        class DeferredThread:
            def __init__(self, *, target, **_kwargs):
                targets.append(target)

            def start(self) -> None:
                pass

        with (
            patch.object(memory_metrics, "_GPU_CACHED_AT", 10.0),
            patch.object(memory_metrics, "_GPU_CACHED_VALUE", 25.0),
            patch.object(memory_metrics, "_GPU_IN_FLIGHT", False),
            patch.object(memory_metrics.threading, "Thread", DeferredThread),
            patch.object(memory_metrics.time, "monotonic", side_effect=[10.9, 11.0]),
        ):
            self.assertEqual(memory_metrics._gpu_utilization(), 25.0)
            self.assertEqual(targets, [])
            self.assertEqual(memory_metrics._gpu_utilization(), 25.0)
            self.assertEqual(len(targets), 1)

    def test_windows_snapshot_does_not_wait_for_process_gpu_memory(self) -> None:
        started = threading.Event()

        class DeferredThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self) -> None:
                started.set()

        with (
            patch.object(memory_metrics.sys, "platform", "win32"),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_CACHED_AT", 0.0),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_CACHED_VALUE", (None, None)),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_IN_FLIGHT", False),
            patch.object(memory_metrics.threading, "Thread", DeferredThread),
            patch.object(memory_metrics, "_physical_memory", return_value=(1000, 500)),
            patch.object(memory_metrics, "_scena_footprint", return_value=100),
            patch.object(memory_metrics, "_gpu_utilization", return_value=42),
            patch.object(memory_metrics, "_gpu_memory", return_value=(200, 800)),
            patch.object(memory_metrics, "_accelerator_topology", return_value={"kind": "dedicated", "adapterId": "gpu-1", "dedicatedBytes": 800}),
            patch("server.modules.resource_coordinator.memory_ownership", return_value={"owner": None}),
            patch("server.modules.local_llm_metrics.local_llm_metal_memory", return_value=0),
            patch("server.modules.inference.tts_metal_memory", return_value=0),
        ):
            snapshot = memory_metrics.memory_snapshot()

        self.assertTrue(started.is_set())
        self.assertEqual(snapshot["kind"], "split")
        self.assertEqual(snapshot["ram"]["totalBytes"], 1000)
        self.assertEqual(snapshot["vram"]["totalBytes"], 800)
        self.assertEqual(snapshot["vram"]["availableBytes"], 600)
        self.assertEqual(snapshot["gpuUtilizationPercent"], 42)
        self.assertIsNone(snapshot["vram"]["llmBytes"])
        self.assertIsNone(snapshot["vram"]["ttsBytes"])
        self.assertIsNone(snapshot["vram"]["otherUsedBytes"])

    def test_fresh_windows_snapshot_measures_vram_before_the_first_cache(self) -> None:
        # The startup TTS decision may be the first snapshot; the cached path then has no VRAM sample yet.
        class DeferredThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self) -> None:
                pass

        with (
            patch.object(memory_metrics.sys, "platform", "win32"),
            patch.object(memory_metrics, "_GPU_MEMORY_CACHED_AT", 0.0),
            patch.object(memory_metrics, "_GPU_MEMORY_CACHED_VALUE", None),
            patch.object(memory_metrics, "_GPU_MEMORY_IN_FLIGHT", False),
            patch.object(memory_metrics.threading, "Thread", DeferredThread),
            patch.object(memory_metrics, "_physical_memory", return_value=(1000, 500)),
            patch.object(memory_metrics, "_scena_footprint", return_value=100),
            patch.object(memory_metrics, "_gpu_utilization", return_value=None),
            patch.object(memory_metrics, "_gpu_runtime_memory", return_value=(None, None)),
            patch.object(memory_metrics, "_accelerator_topology", return_value={"kind": "dedicated", "adapterId": "gpu-1", "dedicatedBytes": 800}),
            patch("server.modules.windows_gpu.gpu_memory", return_value=(200, 800)),
            patch("server.modules.resource_coordinator.memory_ownership", return_value={"owner": None}),
            patch("server.modules.local_llm_metrics.local_llm_metal_memory", return_value=0),
            patch("server.modules.inference.tts_metal_memory", return_value=0),
        ):
            cached = memory_metrics.memory_snapshot()
            fresh = memory_metrics.fresh_memory_snapshot()

        self.assertIsNone(cached["vram"]["availableBytes"])
        self.assertEqual(fresh["vram"]["availableBytes"], 600)

    def test_process_gpu_memory_refresh_is_single_and_publishes_cache(self) -> None:
        targets = []

        class DeferredThread:
            def __init__(self, *, target, **_kwargs):
                targets.append(target)

            def start(self) -> None:
                pass

        with (
            patch.object(memory_metrics.sys, "platform", "win32"),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_CACHED_AT", 0.0),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_CACHED_VALUE", (None, None)),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_IN_FLIGHT", False),
            patch.object(memory_metrics.threading, "Thread", DeferredThread),
            patch.object(memory_metrics.time, "monotonic", return_value=10.0),
            patch.object(memory_metrics, "_measure_gpu_runtime_memory", return_value=(30, 80)),
        ):
            self.assertEqual(memory_metrics._gpu_runtime_memory(), (None, None))
            self.assertEqual(memory_metrics._gpu_runtime_memory(), (None, None))
            self.assertEqual(len(targets), 1)
            targets[0]()
            self.assertEqual(memory_metrics._gpu_runtime_memory(), (30, 80))

    def test_failed_process_gpu_memory_refresh_retries_after_cache_boundary(self) -> None:
        starts = []

        class DeferredThread:
            def __init__(self, *, target, **_kwargs):
                self.target = target

            def start(self) -> None:
                starts.append(self.target)

        with (
            patch.object(memory_metrics.sys, "platform", "win32"),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_CACHED_AT", 0.0),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_CACHED_VALUE", (None, None)),
            patch.object(memory_metrics, "_GPU_RUNTIME_MEMORY_IN_FLIGHT", False),
            patch.object(memory_metrics.threading, "Thread", DeferredThread),
            patch.object(memory_metrics, "_measure_gpu_runtime_memory", side_effect=OSError),
            patch.object(memory_metrics.time, "monotonic", side_effect=[10.0, 14.9, 15.0]),
        ):
            memory_metrics._gpu_runtime_memory()
            starts.pop()()
            memory_metrics._gpu_runtime_memory()
            self.assertEqual(len(starts), 0)
            memory_metrics._gpu_runtime_memory()
            self.assertEqual(len(starts), 1)

    def test_macos_does_not_start_process_gpu_memory_refresh(self) -> None:
        with (
            patch.object(memory_metrics.sys, "platform", "darwin"),
            patch.object(memory_metrics.threading, "Thread") as thread,
        ):
            self.assertEqual(memory_metrics._gpu_runtime_memory(), (None, None))
        thread.assert_not_called()

    def test_gpu_collector_failure_returns_unavailable(self) -> None:
        with patch.object(memory_metrics, "_measure_gpu_utilization", side_effect=OSError):
            memory_metrics._refresh_gpu_utilization()
        self.assertIsNone(memory_metrics._GPU_CACHED_VALUE)

    def test_gpu_command_failure_does_not_prevent_memory_snapshot(self) -> None:
        with (
            patch.object(memory_metrics, "_physical_memory", return_value=(1000, 500)),
            patch.object(memory_metrics, "_scena_footprint", return_value=100),
            patch.object(memory_metrics, "_gpu_utilization", return_value=None),
            patch.object(memory_metrics, "_gpu_memory", return_value=None),
            patch.object(memory_metrics, "_gpu_runtime_memory", return_value=(None, None)),
            patch("server.modules.resource_coordinator.memory_ownership", return_value={"owner": None}),
            patch("server.modules.local_llm_metrics.local_llm_metal_memory", return_value=0),
            patch("server.modules.inference.tts_metal_memory", return_value=0),
        ):
            snapshot = memory_metrics.memory_snapshot()
        self.assertEqual(snapshot["totalBytes"], 1000)
        self.assertIsNone(snapshot["gpuUtilizationPercent"])

    def test_physical_memory_uses_cached_total_and_psutil_availability(self) -> None:
        with (
            patch.object(memory_metrics, "_TOTAL_MEMORY", 1000),
            patch.object(memory_metrics.psutil, "virtual_memory", return_value=SimpleNamespace(available=1200)),
        ):
            self.assertEqual(memory_metrics._physical_memory(), (1000, 1000))

    def test_footprint_starts_at_the_tauri_parent(self) -> None:
        root = SimpleNamespace(pid=10, memory_info=lambda: SimpleNamespace(rss=100), parents=lambda: [])
        child = SimpleNamespace(pid=20, memory_info=lambda: SimpleNamespace(rss=50), parents=lambda: [root])
        grandchild = SimpleNamespace(pid=30, memory_info=lambda: SimpleNamespace(rss=25), parents=lambda: [child, root])
        root.children = lambda recursive: [child, grandchild]
        with (
            patch.dict(os.environ, {"SCENA_PARENT_PID": "10"}),
            patch.object(memory_metrics.psutil, "pid_exists", return_value=True),
            patch.object(memory_metrics.psutil, "Process", return_value=root),
            patch.object(memory_metrics, "_model_runtime_pids", return_value=set()),
        ):
            self.assertEqual(memory_metrics._scena_footprint(), 175)

    def test_footprint_excludes_tts_worker_and_its_descendants(self) -> None:
        root = SimpleNamespace(pid=10, memory_info=lambda: SimpleNamespace(rss=100), parents=lambda: [])
        child = SimpleNamespace(pid=15, memory_info=lambda: SimpleNamespace(rss=50), parents=lambda: [root])
        worker = SimpleNamespace(pid=20, memory_info=lambda: SimpleNamespace(rss=1000), parents=lambda: [child, root])
        grandchild = SimpleNamespace(pid=30, memory_info=lambda: SimpleNamespace(rss=500), parents=lambda: [worker, child, root])
        root.children = lambda recursive: [child, worker, grandchild]
        with (
            patch.dict(os.environ, {"SCENA_PARENT_PID": "10"}),
            patch.object(memory_metrics.psutil, "pid_exists", return_value=True),
            patch.object(memory_metrics.psutil, "Process", return_value=root),
            patch.object(memory_metrics, "_model_runtime_pids", return_value={20}),
        ):
            self.assertEqual(memory_metrics._scena_footprint(), 150)

    def test_snapshot_removes_scena_overlap_and_clamps_other_usage(self) -> None:
        with (
            patch.object(memory_metrics, "_physical_memory", return_value=(1000, 300)),
            patch.object(memory_metrics, "_scena_footprint", return_value=200),
            patch("server.modules.resource_coordinator.memory_ownership", return_value={"owner": "tts"}),
            patch("server.modules.local_llm_metrics.local_llm_metal_memory", return_value=30),
            patch("server.modules.inference.tts_metal_memory", return_value=80),
            patch.object(memory_metrics, "_gpu_utilization", return_value=37),
            patch.object(memory_metrics, "_gpu_memory", return_value=(200, 1000)),
            patch.object(memory_metrics, "_gpu_runtime_memory", return_value=(30, 80)),
            patch.object(memory_metrics, "_accelerator_topology", return_value={"kind": "unified", "adapterId": "metal-default", "dedicatedBytes": None}),
        ):
            snapshot = memory_metrics.memory_snapshot()
        self.assertEqual(snapshot["kind"], "unified")
        self.assertEqual(snapshot["otherUsedBytes"], 390)
        self.assertEqual(snapshot["scenaAppBytes"], 200)
        self.assertEqual(snapshot["llmBytes"], 30)
        self.assertEqual(snapshot["ttsBytes"], 80)
        self.assertEqual(snapshot["metalOwner"], "tts")
        self.assertEqual(snapshot["gpuUtilizationPercent"], 37)

    def test_snapshot_clamps_segments_to_used_memory(self) -> None:
        with (
            patch.object(memory_metrics, "_physical_memory", return_value=(1000, 900)),
            patch.object(memory_metrics, "_scena_footprint", return_value=400),
            patch("server.modules.resource_coordinator.memory_ownership", return_value={"owner": "llm"}),
            patch("server.modules.local_llm_metrics.local_llm_metal_memory", return_value=300),
            patch("server.modules.inference.tts_metal_memory", return_value=50),
            patch.object(memory_metrics, "_gpu_utilization", return_value=None),
            patch.object(memory_metrics, "_gpu_memory", return_value=None),
            patch.object(memory_metrics, "_gpu_runtime_memory", return_value=(None, None)),
        ):
            snapshot = memory_metrics.memory_snapshot()
        self.assertEqual(snapshot["availableBytes"], 250)
        self.assertEqual(snapshot["llmBytes"], 300)
        self.assertEqual(snapshot["ttsBytes"], 50)
        self.assertEqual(snapshot["scenaAppBytes"], 400)
        self.assertEqual(snapshot["otherUsedBytes"], 0)

    def test_zero_gpu_utilization_replaces_the_startup_sample(self) -> None:
        with (
            patch.object(memory_metrics, "_physical_memory", return_value=(1000, 500)),
            patch.object(memory_metrics, "_scena_footprint", return_value=100),
            patch.object(memory_metrics, "_gpu_utilization", return_value=0),
            patch.object(memory_metrics, "_gpu_memory", return_value=None),
            patch.object(memory_metrics, "_gpu_runtime_memory", return_value=(None, None)),
            patch.object(
                memory_metrics,
                "_accelerator_topology",
                return_value={"kind": "unified", "adapterId": "metal-default", "dedicatedBytes": None, "gpuUtilizationPercent": 70},
            ),
            patch("server.modules.resource_coordinator.memory_ownership", return_value={"owner": None}),
            patch("server.modules.local_llm_metrics.local_llm_metal_memory", return_value=0),
            patch("server.modules.inference.tts_metal_memory", return_value=0),
        ):
            self.assertEqual(memory_metrics.memory_snapshot()["gpuUtilizationPercent"], 0)

    def test_unavailable_measurements_stay_unknown(self) -> None:
        with (
            patch.object(memory_metrics, "_physical_memory", return_value=(None, None)),
            patch.object(memory_metrics, "_scena_footprint", return_value=None),
            patch("server.modules.resource_coordinator.memory_ownership", return_value={"owner": "tts"}),
            patch("server.modules.local_llm_metrics.local_llm_metal_memory", return_value=0),
            patch("server.modules.inference.tts_metal_memory", return_value=None),
            patch.object(memory_metrics, "_gpu_utilization", return_value=None),
            patch.object(memory_metrics, "_gpu_memory", return_value=None),
            patch.object(memory_metrics, "_gpu_runtime_memory", return_value=(None, None)),
        ):
            snapshot = memory_metrics.memory_snapshot()
        self.assertIsNone(snapshot["totalBytes"])
        self.assertIsNone(snapshot["otherUsedBytes"])
        self.assertIsNone(snapshot["scenaAppBytes"])


if __name__ == "__main__":
    unittest.main()

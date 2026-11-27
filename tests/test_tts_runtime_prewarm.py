from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import llm_registry, memory_metrics, tts_registry, tts_runtime


class TtsRuntimePrewarmTests(unittest.TestCase):
    def setUp(self):
        self.status = dict(tts_runtime._STATUS)
        self.epoch = tts_runtime._EPOCH
        self.last_interaction = tts_runtime._LAST_INTERACTION

    def tearDown(self):
        tts_runtime._STATUS.clear()
        tts_runtime._STATUS.update(self.status)
        tts_runtime._EPOCH = self.epoch
        tts_runtime._LAST_INTERACTION = self.last_interaction

    def test_startup_loads_without_waiting_for_ui_quiet(self):
        # The owner's rule: startup loading begins at once, even right after a click, and runs in the background.
        prepared = []
        with patch.object(tts_runtime, "_selected_model_id", return_value="selected"), patch.object(
            tts_runtime, "_post_draft_policy", return_value=(True, True, "coexistence-vram-available"),
        ), patch.object(tts_runtime, "deps", SimpleNamespace(
            active_draft_job=lambda: False, active_export_job=lambda: False,
            memory_ownership=lambda: {"owner": None},
            prepare_irodori_worker=lambda **kwargs: prepared.append(kwargs),
            start_cuda_calibration=lambda *_args: None,
        )), patch.object(tts_runtime.time, "sleep", side_effect=AssertionError("startup waited for UI quiet")), patch.object(
            tts_runtime.threading, "Thread",
        ) as thread:
            tts_runtime.start_tts_prepare(startup=True)
            tts_runtime.note_tts_interaction()
            thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])
        self.assertEqual(prepared, [{"coexist": True}])
        self.assertEqual(tts_runtime.tts_runtime_status()["state"], "ready")

    def test_calibration_continues_only_while_ready_idle_and_without_llm(self):
        clock = [200.0]
        owner = [None]
        with patch.object(tts_runtime, "_LAST_INTERACTION", 199.0), patch.dict(tts_runtime._STATUS, state="ready", modelId="selected"), patch.object(
            tts_runtime.time, "monotonic", side_effect=lambda: clock[0],
        ), patch.object(tts_runtime.time, "sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)), patch.object(
            tts_runtime, "deps", SimpleNamespace(memory_ownership=lambda: {"owner": owner[0]}),
        ):
            self.assertTrue(tts_runtime._calibration_may_continue("selected"))
            self.assertGreaterEqual(clock[0], 200.5)
            self.assertFalse(tts_runtime._calibration_may_continue("other"))
            owner[0] = "llm"
            self.assertFalse(tts_runtime._calibration_may_continue("selected"))
            owner[0] = None
            tts_runtime._STATUS["state"] = "in-use"
            self.assertFalse(tts_runtime._calibration_may_continue("selected"))

    def test_startup_skips_when_loading_would_release_llm(self):
        with patch.object(tts_runtime, "_selected_model_id", return_value="selected"), patch.object(
            tts_runtime, "_post_draft_policy", return_value=(True, False, "scena-llm-release-required"),
        ), patch.object(
            tts_runtime, "deps", SimpleNamespace(
                active_draft_job=lambda: False, active_export_job=lambda: False,
                memory_ownership=lambda: {"owner": None},
            ),
        ), patch.object(tts_runtime.threading, "Thread") as thread:
            tts_runtime.start_tts_prepare(startup=True)
            thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])
            status = tts_runtime.tts_runtime_status()
        self.assertEqual(status["state"], "skipped")
        self.assertEqual(status["preparationReason"], "startup-would-release-llm")

    def test_startup_queues_coexisting_worker(self):
        prepared = []
        with patch.object(tts_runtime, "_selected_model_id", return_value="selected"), patch.object(
            tts_runtime, "_post_draft_policy", return_value=(True, True, "coexistence-vram-available"),
        ), patch.object(
            tts_runtime, "deps", SimpleNamespace(
                active_draft_job=lambda: False, active_export_job=lambda: False,
                memory_ownership=lambda: {"owner": None},
                prepare_irodori_worker=lambda **kwargs: prepared.append(kwargs),
                start_cuda_calibration=lambda model_id, _should_continue: prepared.append(("calibrate", model_id)),
            ),
        ), patch.object(tts_runtime.threading, "Thread") as thread:
            status = tts_runtime.start_tts_prepare(startup=True)
            self.assertEqual(status["state"], "preparing")
            self.assertEqual(thread.call_args.kwargs["args"][2:], (False, True))
            thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])
        self.assertEqual(prepared, [{"coexist": True}, ("calibrate", "selected")])
        self.assertEqual(tts_runtime.tts_runtime_status()["state"], "ready")

    def test_generation_cancels_queued_startup_prepare(self):
        with patch.object(tts_runtime, "_selected_model_id", return_value="selected"), patch.object(
            tts_runtime.threading, "Thread",
        ) as thread, patch.object(tts_runtime, "deps", SimpleNamespace(prepare_irodori_worker=lambda **_kw: self.fail(
            "background preparation ran after generation started"),
        )):
            tts_runtime.start_tts_prepare(startup=True)
            tts_runtime.mark_tts_in_use("selected")
            thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])
        self.assertEqual(tts_runtime.tts_runtime_status()["state"], "in-use")

    def test_startup_skips_during_llm_work(self):
        with patch.object(tts_runtime, "_selected_model_id", return_value="selected"), patch.object(tts_runtime, "deps", SimpleNamespace(
            active_draft_job=lambda: True, active_export_job=lambda: False,
            memory_ownership=lambda: {"owner": "llm"},
        )), patch.object(tts_runtime.threading, "Thread") as thread:
            tts_runtime.start_tts_prepare(startup=True)
            thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])
        self.assertEqual(tts_runtime.tts_runtime_status()["preparationReason"], "startup-resource-busy")

    def test_startup_without_installed_model_stays_stopped(self):
        with patch.object(tts_runtime, "_selected_model_id", return_value=None), patch.object(
            tts_runtime.threading, "Thread",
        ) as thread:
            status = tts_runtime.start_tts_prepare(startup=True)
        self.assertEqual(status["state"], "stopped")
        self.assertIsNone(status["error"])
        thread.assert_not_called()

    def policy(self, *, available: int, provider: str):
        gib = 1024 ** 3
        runtime = {"model": {"requiredVramBytes": 4 * gib}}
        snapshot = {"kind": "split", "vram": {"totalBytes": 12 * gib, "availableBytes": available}}
        with patch.object(tts_runtime.sys, "platform", "win32"), patch.object(
            tts_registry, "selected_tts_runtime", return_value=runtime,
        ), patch.object(memory_metrics, "fresh_memory_snapshot", return_value=snapshot), patch.object(
            llm_registry, "resolve_default_llm", return_value={"provider": provider},
        ):
            return tts_runtime._post_draft_policy()

    def test_enough_vram_retains_llm(self):
        self.assertEqual(self.policy(available=6 * 1024 ** 3, provider="scena-local"),
                         (True, True, "coexistence-vram-available"))

    def test_low_vram_releases_only_scena_owned_llm(self):
        self.assertEqual(self.policy(available=4 * 1024 ** 3, provider="scena-local"),
                         (True, False, "scena-llm-release-required"))
        self.assertEqual(self.policy(available=4 * 1024 ** 3, provider="ollama"),
                         (False, False, "external-llm-retained-vram-insufficient"))

    def test_unknown_vram_requirement_skips(self):
        with patch.object(tts_runtime.sys, "platform", "win32"), patch.object(
            tts_registry, "selected_tts_runtime", return_value={"model": {}},
        ), patch.object(memory_metrics, "fresh_memory_snapshot", return_value={}):
            self.assertEqual(tts_runtime._post_draft_policy(),
                             (False, False, "vram-requirement-unverified"))

    def test_every_cuda_model_has_its_measured_vram_requirement(self):
        # Without a requirement, Windows skips startup preparation and the background CUDA calibration.
        # Values: measured process peak on RTX 4070 Ti (2026-11-24), plus the SCENA CUDA adapter margin
        # for engines that use it, rounded up to 0.5 GiB.
        from server.modules import tts_catalog, tts_large_assets, tts_windows_quantized_variants as quantized
        gib = 1024 ** 3
        expected = {
            tts_catalog.MODEL_REVISION: 8 * gib, tts_catalog.V4_SMALL_REVISION: 8 * gib,
            tts_catalog.ANIME_MODEL_REVISION: 8 * gib,
            quantized.QUANTIZED_REPOS[tts_catalog.MODEL_REPO]["revision"]: int(5.5 * gib),
            quantized.QUANTIZED_REPOS["Aratako/Irodori-TTS-v4-Small"]["revision"]: int(5.5 * gib),
            tts_large_assets.LARGE_QUANTIZED_REVISION: int(9.5 * gib),
            tts_catalog.MEANFLOW_MODEL_REVISION: int(6.5 * gib),
            "e863a3a93e652e09afeff3e84823a206a0a60314": int(7.5 * gib),
            "236c1e56591279fc24e3c1bf6609fc06e48dde28": int(6.5 * gib),
        }
        self.assertEqual(tts_catalog.VERIFIED_VRAM_REQUIREMENTS, expected)
        installable = {item["revision"] for item in tts_catalog.tts_catalog()["models"]}
        for base in quantized.QUANTIZED_REPOS:
            installable.update(variant["revision"] for variant in quantized.windows_quantized_variants(base, (8, 9)))
        # Large FP32 alone is larger than a 12 GB GPU, so it stays unverified and never preloads.
        self.assertEqual(installable - set(expected), {tts_catalog.LARGE_MODEL_REVISION})

if __name__ == "__main__":
    unittest.main()

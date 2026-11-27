from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from fastapi import HTTPException
from fastapi.testclient import TestClient

from server.modules import llm_registry as registry, model_runtime_jobs as jobs
from server.modules import local_llm_runtime as runtime, omlx_environment as env
from server.modules import llm_model_tests as probes, llm_runtime_binding as binding
from server.modules.llm_session_usage import begin_llm_operation, finish_llm_operation, reset_session_usage, llm_operation, operation_llm_selection


class ModelRuntimeBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for target, value in [
            ("server.modules.constants.LOCAL_LLM_ROOT", self.root),
            ("server.modules.constants.DATA_ROOT", self.root),
            ("server.modules.llm_registry.REGISTRY_FILE", self.root / "cards.json"),
            ("server.modules.model_runtime_jobs.JOBS", {}),
            ("server.modules.model_runtime_jobs.CANCEL", {}),
            ("server.modules.omlx_environment._JOB", {"state": "idle", "message": "", "runtimeId": None}),
            ("server.modules.llm_model_tests.MODEL_TESTS", {}),
        ]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        probe_patch = patch.object(probes, "_schema_probe", return_value={"state": "unknown", "reasonCode": None})
        probe_patch.start()
        self.addCleanup(probe_patch.stop)
        reset_session_usage()
        self.addCleanup(reset_session_usage)
        self.endpoint = registry.create_llm_endpoint({"provider": "scena-local"})

    def card(self, name="one", runtime_id="old"):
        model = self.root / "models" / name
        model.mkdir(parents=True, exist_ok=True)
        (model / "config.json").write_text('{}')
        (model / "model.safetensors").write_bytes(b"mock")
        card = registry.create_llm_card({"endpointId": self.endpoint["id"], "modelId": name,
            "source": "managed", "localMetadata": {"path": str(model)}})
        value = registry.read_llm_registry()
        value["cards"][-1]["runtimeId"] = runtime_id
        value["cards"][-1]["testStatus"] = {"state": "passed", "checkedAt": 1, "errorCategory": None}
        registry.write_llm_registry(value)
        return {**card, "runtimeId": runtime_id}

    def install(self, runtime_id):
        path = env._runtime_path(runtime_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / ".ready").write_text('{}')
        (path / "scena-launcher.py").write_text('# pinned launcher')
        value = env._read_registry()
        value["runtimes"].append({"id": runtime_id, "path": str(path), "state": "ready", "diskBytes": 4,
                                   "omlxVersion": "mock", "source": "scena"})
        env._write_registry(value)
        return path

    def queue(self, card, target="new"):
        with patch.object(jobs.threading, "Thread"):
            return jobs.start_model_runtime(card["id"], target)

    def run_job(self, card, **mocks):
        with patch.object(runtime, "load_local_llm", **mocks) as load, \
             patch.object(runtime, "stop_local_llm"), \
             patch.object(runtime, "local_llm_runtime_endpoint", return_value="http://mock/v1"), \
             patch.object(probes, "_completion", return_value="接続確認済み"):
            jobs._run(jobs.JOBS[card["id"]], jobs.CANCEL[card["id"]])
        return load

    def test_migration_preserves_selected_missing_runtime_without_starting(self):
        card = self.card()
        value = registry.read_llm_registry()
        value["version"] = 3
        value["cards"][0].pop("runtimeId")
        registry.REGISTRY_FILE.write_text(json.dumps(value))
        env._write_registry({"activeRuntimeId": "missing-old", "runtimes": []})
        with patch.object(env, "install_omlx_runtime") as install, patch.object(runtime, "start_local_llm") as start:
            self.assertEqual(registry.read_llm_registry()["cards"][0]["runtimeId"], "missing-old")
            env._write_registry({"activeRuntimeId": "changed", "runtimes": []})
            self.assertEqual(registry.read_llm_registry()["cards"][0]["runtimeId"], "missing-old")
            self.assertEqual(jobs.model_runtime_status({**card, "runtimeId": "missing-old"})["state"], "missing")
        install.assert_not_called()
        start.assert_not_called()

    def test_app_update_affects_only_new_cards(self):
        old = self.card()
        with patch.object(binding, "recommended_id", return_value="updated"), \
             patch.object(registry, "recommended_id", return_value="updated"):
            new = registry.create_llm_card({"endpointId": self.endpoint["id"], "modelId": "two", "source": "managed"})
        cards = registry.read_llm_registry()["cards"]
        self.assertEqual([x["runtimeId"] for x in cards], [old["runtimeId"], new["runtimeId"]])
        self.assertEqual(new["runtimeId"], "updated")

    def test_external_registration_has_no_runtime_side_effects(self):
        endpoint = registry.create_llm_endpoint({"provider": "ollama", "baseUrl": "http://mock/v1"})
        with patch.object(env, "install_omlx_runtime") as install, patch.object(runtime, "start_local_llm") as start:
            card = registry.create_remote_llm_card({"endpointId": endpoint["id"], "modelId": "remote"})
            self.assertNotIn("runtimeId", card)
            with self.assertRaises(HTTPException):
                jobs.start_model_runtime(card["id"])
        install.assert_not_called()
        start.assert_not_called()

    def test_switch_commits_only_target_after_short_generation(self):
        one, two = self.card(), self.card("two")
        self.install("new")
        self.queue(one)
        load = self.run_job(one)
        cards = registry.read_llm_registry()["cards"]
        self.assertEqual([x["runtimeId"] for x in cards], ["new", "old"])
        self.assertEqual(cards[1]["testStatus"], {"state": "passed", "checkedAt": 1, "errorCategory": None})
        self.assertEqual(load.call_args.kwargs["runtime_id"], "new")
        self.assertEqual(jobs.JOBS[one["id"]]["state"], "complete")
        self.assertEqual(two["runtimeId"], "old")

    def test_startup_failure_and_cancellation_preserve_previous_binding(self):
        card = self.card()
        self.install("new")
        self.queue(card)
        self.run_job(card, side_effect=RuntimeError("startup failed"))
        self.assertEqual(jobs.JOBS[card["id"]]["state"], "failed")
        self.assertEqual(registry.read_llm_registry()["cards"][0]["runtimeId"], "old")
        self.queue(card)
        jobs.cancel_model_runtime(card["id"])
        load = self.run_job(card)
        load.assert_not_called()
        self.assertEqual(jobs.JOBS[card["id"]]["state"], "cancelled")
        self.assertEqual(registry.read_llm_registry()["cards"][0]["runtimeId"], "old")

    def test_completion_failure_does_not_change_test_results(self):
        card = self.card()
        self.install("new")
        self.queue(card)
        before = registry.read_llm_registry()
        with patch.object(runtime, "load_local_llm"), patch.object(runtime, "stop_local_llm"), \
             patch.object(runtime, "local_llm_runtime_endpoint", return_value="http://mock"), \
             patch.object(probes, "_completion", side_effect=ValueError("invalid response")):
            jobs._run(jobs.JOBS[card["id"]], jobs.CANCEL[card["id"]])
        self.assertEqual(registry.read_llm_registry(), before)
        self.assertEqual(jobs.JOBS[card["id"]]["state"], "failed")

    def test_shared_install_is_reused_and_waiter_cancel_does_not_cancel_other_model(self):
        one, two = self.card(runtime_id=binding.recommended_id()), self.card("two", binding.recommended_id())
        self.queue(one, one["runtimeId"])
        self.queue(two, two["runtimeId"])
        jobs.cancel_model_runtime(one["id"])
        def install(*_args, **_kwargs):
            self.install(two["runtimeId"])
            env._JOB.update(state="complete")
        with patch.object(env, "install_omlx_runtime", side_effect=install) as fetch:
            with self.assertRaises(InterruptedError):
                jobs._ensure(jobs.JOBS[one["id"]], jobs.CANCEL[one["id"]])
            jobs._ensure(jobs.JOBS[two["id"]], jobs.CANCEL[two["id"]])
            jobs._ensure(jobs.JOBS[two["id"]], jobs.CANCEL[two["id"]])
        fetch.assert_called_once()

    def test_registered_reference_and_pending_job_protect_runtime_via_api(self):
        card = self.card()
        self.install("old")
        self.install("new")
        client = TestClient(server.app.app)
        self.assertEqual(client.delete('/api/local-llm/runtimes/old').status_code, 409)
        self.queue(card)
        self.assertEqual(client.delete('/api/local-llm/runtimes/new').status_code, 409)
        with patch.object(runtime, "unload_local_llm"), patch.object(runtime, "local_llm_runtime_pid", return_value=None):
            jobs.JOBS[card["id"]]["state"] = "cancelled"
            registry.delete_llm_card(card["id"])
            self.assertEqual(client.delete('/api/local-llm/runtimes/old').status_code, 200)
        self.assertTrue(env._runtime_path("new").exists())

    def test_concurrent_registration_keeps_every_card(self):
        ready = threading.Barrier(4)
        def register(index):
            name = str(index)
            model = self.root / "models" / name
            model.mkdir(parents=True)
            (model / "config.json").write_text('{}')
            (model / "model.safetensors").write_bytes(b"mock")
            ready.wait(timeout=5)
            return registry.create_llm_card({
                "endpointId": self.endpoint["id"], "modelId": name,
                "source": "managed", "localMetadata": {"path": str(model)},
            })
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(register, range(8)))
        cards = registry.read_llm_registry()["cards"]
        self.assertEqual({card["modelId"] for card in cards}, {str(index) for index in range(8)})
        self.assertEqual({card["id"] for card in cards}, {card["id"] for card in results})

    def test_restart_restores_interrupted_job_without_install(self):
        card = self.card()
        self.install("new")
        self.queue(card)
        jobs.JOBS.clear()
        with patch.object(env, "install_omlx_runtime") as install:
            state = jobs.model_runtime_status(card)
        self.assertEqual(state["job"]["state"], "interrupted")
        install.assert_not_called()
        self.queue(card)
        self.run_job(card)
        self.assertEqual(jobs.JOBS[card["id"]]["state"], "complete")

    def test_running_operation_blocks_switch_and_probe_without_stopping(self):
        card = self.card()
        self.install("new")
        begin_llm_operation("job", "local generation", "scena-local", "one")
        with patch.object(runtime, "stop_local_llm") as stop:
            with self.assertRaises(HTTPException):
                self.queue(card)
            with self.assertRaises(HTTPException):
                probes.start_llm_model_test(card["id"])
        stop.assert_not_called()
        finish_llm_operation("job", "completed")

    def test_runtime_command_uses_each_model_binding(self):
        one, two = self.card(), self.card("two", "new")
        old_path, new_path = self.install("old"), self.install("new")
        self.assertEqual(runtime._runtime_command(binding.model_runtime(one["modelId"]))[0], str(old_path / "bin/python"))
        self.assertEqual(runtime._runtime_command(binding.model_runtime(two["modelId"]))[0], str(new_path / "bin/python"))
        with self.assertRaises(HTTPException):
            env.switch_omlx_runtime("new")

    def test_unsafe_directory_cannot_be_deleted(self):
        outside = self.root / "model-data"
        outside.mkdir()
        env._write_registry({"runtimes": [{"id": "unsafe", "path": str(outside)}]})
        with self.assertRaises(HTTPException) as raised:
            env.delete_omlx_runtime("unsafe")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertTrue(outside.exists())

    def test_cancel_during_shared_fetch_keeps_the_other_waiter(self):
        runtime_id = binding.recommended_id()
        one, two = self.card(runtime_id=runtime_id), self.card("two", runtime_id)
        self.queue(one, runtime_id)
        self.queue(two, runtime_id)
        started, completed = threading.Event(), threading.Event()
        def install(*_args, **_kwargs):
            env._JOB.update(state="downloading")
            started.set()
        with patch.object(env, "install_omlx_runtime", side_effect=install) as fetch:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(jobs._ensure, jobs.JOBS[one["id"]], jobs.CANCEL[one["id"]])
                self.assertTrue(started.wait(2))
                second = pool.submit(jobs._ensure, jobs.JOBS[two["id"]], jobs.CANCEL[two["id"]])
                jobs.cancel_model_runtime(one["id"])
                with self.assertRaises(InterruptedError):
                    first.result(timeout=2)
                self.install(runtime_id)
                env._JOB.update(state="complete")
                second.result(timeout=2)
                completed.set()
        self.assertTrue(completed.is_set())
        fetch.assert_called_once()

    def test_download_failure_preserves_binding_and_registered_model(self):
        card = self.card(runtime_id=binding.recommended_id())
        self.queue(card, card["runtimeId"])
        def fail(*_args, **_kwargs):
            env._JOB.update(state="failed", message="download failed")
        with patch.object(env, "install_omlx_runtime", side_effect=fail):
            self.run_job(card)
        self.assertEqual(jobs.JOBS[card["id"]]["state"], "failed")
        self.assertEqual(registry.read_llm_registry()["cards"][0]["runtimeId"], card["runtimeId"])
        self.assertTrue(Path(card["localMetadata"]["path"]).exists())

    def test_operation_keeps_its_card_and_runtime_when_default_changes(self):
        one, two = self.card(), self.card("two", "new")
        registry.set_default_llm_card(one["id"])
        with llm_operation("fixed local operation"):
            registry.set_default_llm_card(two["id"])
            selected = operation_llm_selection()
            self.assertEqual((selected["cardId"], selected["runtimeId"]), (one["id"], "old"))
            with self.assertRaises(HTTPException):
                jobs.start_model_runtime(one["id"], "new")

    def test_verification_cleanup_remains_exclusive_after_binding_commit(self):
        card = self.card()
        self.install("new")
        self.queue(card)
        def stop():
            self.assertEqual(jobs.JOBS[card["id"]]["state"], "complete")
            with self.assertRaises(HTTPException):
                begin_llm_operation("concurrent", "local generation", "scena-local", "one")
        with patch.object(runtime, "load_local_llm"), patch.object(runtime, "stop_local_llm", side_effect=stop),              patch.object(runtime, "local_llm_runtime_endpoint", return_value="http://mock"),              patch.object(probes, "_completion", return_value="接続確認済み"):
            jobs._run(jobs.JOBS[card["id"]], jobs.CANCEL[card["id"]])
        self.assertEqual(jobs.JOBS[card["id"]]["state"], "complete")
        self.assertFalse(jobs.active_jobs())

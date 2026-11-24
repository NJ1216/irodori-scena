import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.app_deps import HTTPException
from fastapi.testclient import TestClient
from server.modules import huggingface_models as hf, model_runtime_jobs as jobs
from server.modules import llm_registry as registry, llama_cpp_runtime as runtime
from server.modules import llm_model_tests as probes
from server.modules.llm_probe_response import ProbeResponseError


class WindowsModelAdditionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        patches = {
            "server.modules.huggingface_preparation.WINDOWS_MODEL_ADDITION": True,
            "server.modules.constants.DATA_ROOT": self.root,
            "server.modules.constants.LOCAL_LLM_ROOT": self.root / "llm",
            "server.modules.llm_registry.REGISTRY_FILE": self.root / "cards.json",
            "server.modules.model_runtime_jobs.JOBS": {},
            "server.modules.model_runtime_jobs.CANCEL": {},
            "server.modules.huggingface_models.HF_DOWNLOADS": {},
            "server.modules.huggingface_models.HF_CANCEL": {},
        }
        for target, value in patches.items():
            self.stack.enter_context(patch(target, value))
        self.stack.enter_context(patch.object(hf, "WINDOWS_MODEL_CATALOG", True))
        self.stack.enter_context(patch.object(hf.sys, "platform", "win32"))
        self.stack.enter_context(patch.object(runtime, "selected_backend", return_value="cpu"))
        self.stack.enter_context(patch.object(runtime, "recommended_backend", return_value="cpu"))
        self.status = {"ready": False, "version": "test", "backend": "cpu", "job": {"state": "idle"}}
        self.stack.enter_context(patch.object(runtime, "llama_cpp_runtime_status", side_effect=lambda *_: self.status))
        self.install = self.stack.enter_context(patch.object(runtime, "install_llama_cpp_runtime", side_effect=self.installed))
        original_start = threading.Thread.start
        self.stack.enter_context(patch.object(threading.Thread, "start", autospec=True,
            side_effect=lambda worker: None if worker._target in {jobs._run, hf._download_repo} else original_start(worker)))
        self.info = SimpleNamespace(id="org/model", sha="fixed", tags=["gguf"], library_name="transformers",
                                   siblings=[SimpleNamespace(rfilename="model-Q4.gguf", size=24)])
        self.stack.enter_context(patch.object(hf, "_model_info_with_optional_token", return_value=(self.info, None)))
        self.stack.enter_context(patch.object(hf, "_download_file", side_effect=self.write_model))
        self.stack.enter_context(patch("server.modules.local_llm_runtime.load_local_llm"))
        self.stack.enter_context(patch("server.modules.local_llm_runtime.stop_local_llm"))
        self.stack.enter_context(patch("server.modules.local_llm_runtime.local_llm_runtime_endpoint", return_value="http://test.invalid/v1"))
        self.stack.enter_context(patch("server.modules.local_llm_runtime.local_llm_runtime_api_key", return_value="test"))
        self.completion = self.stack.enter_context(patch.object(probes, "_completion", return_value="ok"))
        self.stack.enter_context(patch.object(probes, "_schema_probe", return_value={"state": "unknown"}))

    def installed(self, backend):
        self.status.update(ready=True, job={"state": "complete"})

    def write_model(self, _repo, name, _revision, target, state, *_args):
        (target / name).write_bytes(b"GGUF" + (3).to_bytes(4, "little") + bytes(16))
        state["downloadedBytes"] = 24

    def begin(self):
        state = hf.start_huggingface_download("org/model", "model-Q4")
        return hf.HF_DOWNLOADS[state["id"]]

    def transfer(self, state):
        hf._download_repo("org/model", state, hf.HF_CANCEL[state["id"]], "model-Q4")
        self.assertEqual(state["state"], "complete")

    def test_both_completion_orders_wait_for_real_preparation_job(self):
        for runtime_first in (True, False):
            with self.subTest(runtime_first=runtime_first):
                state = self.begin()
                job, cancel = jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]]
                if runtime_first:
                    jobs._ensure(job, cancel)
                self.transfer(state)
                self.assertNotEqual(hf.huggingface_download_status(state["id"])["preparation"]["state"], "complete")
                jobs._run(job, cancel)
                self.assertEqual(hf.huggingface_download_status(state["id"])["preparation"]["state"], "complete", job)
                card = registry.read_llm_registry()["cards"][0]
                self.assertEqual(card["testStatus"]["state"], "passed")
                self.assertEqual(card["localMetadata"]["variant"], "model-Q4")
                self.assertEqual(card["localMetadata"]["revision"], "fixed")
                self.status["ready"] = False
        self.assertEqual(self.completion.call_count, 2)

    def test_verification_refreshes_files_pinned_while_waiting(self):
        state = self.begin()
        job, cancel = jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]]
        jobs._ensure(job, cancel)
        with patch.object(jobs, "_wait_model", side_effect=lambda *_: self.transfer(state)):
            jobs._verify_model(job, cancel)
        self.assertEqual(jobs.JOBS[state["cardId"]]["state"], "complete")
        self.completion.assert_called_once()

    def test_failed_verification_is_not_success_and_retry_reuses_model(self):
        state = self.begin()
        self.transfer(state)
        self.completion.side_effect = ValueError("verification failed")
        jobs._run(jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]])
        self.assertEqual(hf.huggingface_download_status(state["id"])["preparation"]["state"], "failed")
        self.completion.side_effect = None
        jobs.start_model_runtime(state["cardId"])
        jobs._run(jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]])
        self.assertEqual(jobs.JOBS[state["cardId"]]["state"], "complete")
        self.assertEqual(self.install.call_count, 1)

    def test_output_limit_keeps_stage_and_category(self):
        state = self.begin()
        self.transfer(state)
        self.completion.side_effect = ProbeResponseError("output_limit", "budget exhausted")
        jobs._run(jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]])
        preparation = hf.huggingface_download_status(state["id"])["preparation"]
        self.assertEqual((preparation["stage"], preparation["errorCategory"]), ("completion", "output_limit"))
        self.assertEqual(preparation["message"], "短い応答確認: 出力上限に達して本文が返りませんでした")

    def test_cancel_after_transfer_prevents_verification_and_keeps_files(self):
        state = self.begin()
        self.transfer(state)
        self.assertEqual(hf.cancel_huggingface_download(state["id"])["preparation"]["state"], "cancelled")
        jobs._run(jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]])
        self.completion.assert_not_called()
        self.assertFalse(jobs._model_download_required(registry.read_llm_registry()["cards"][0]))

    def test_restart_exposes_interrupted_preparation_and_empty_file_list_is_missing(self):
        state = self.begin()
        jobs.JOBS.clear()
        self.assertEqual(hf.huggingface_download_status(state["id"])["preparation"]["state"], "interrupted")
        self.assertEqual(registry.read_llm_registry()["cards"][0]["testStatus"]["state"], "untested")
        self.assertTrue(jobs._model_download_required(registry.read_llm_registry()["cards"][0]))

    def test_duplicate_addition_during_verification_keeps_one_job(self):
        state = self.begin()
        self.transfer(state)
        again = self.begin()
        self.assertEqual(again["id"], state["id"])
        self.assertEqual(len(jobs.JOBS), 1)

    def test_preparation_start_failure_is_exposed(self):
        with patch.object(jobs, "start_model_runtime", side_effect=HTTPException(409, "busy")):
            state = self.begin()
        self.assertEqual(hf.huggingface_download_status(state["id"])["preparation"]["state"], "waiting-model")
        self.transfer(state)
        preparation = hf.huggingface_download_status(state["id"])["preparation"]
        self.assertEqual(preparation["state"], "failed")
        self.assertEqual(preparation["message"], "busy")
        self.assertEqual(registry.read_llm_registry()["cards"][0]["testStatus"]["state"], "failed")

    def test_invalid_gguf_prevents_inference(self):
        state = self.begin()
        self.transfer(state)
        card = registry.read_llm_registry()["cards"][0]
        Path(card["localMetadata"]["files"][0]).write_bytes(b"not gguf")
        jobs._run(jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]])
        self.assertEqual(jobs.JOBS[state["cardId"]]["state"], "failed")
        self.completion.assert_not_called()

    def test_http_status_keeps_file_completion_separate_from_addition(self):
        client = TestClient(server.app.app)
        response = client.post("/api/llm/huggingface/downloads", json={"repoId": "org/model", "variant": "model-Q4"})
        self.assertEqual(response.status_code, 200)
        state = hf.HF_DOWNLOADS[response.json()["id"]]
        self.transfer(state)
        url = f"/api/llm/huggingface/downloads/{state['id']}"
        pending = client.get(url).json()
        self.assertEqual(pending["state"], "complete")
        self.assertEqual(pending["preparation"]["state"], "preparing")
        jobs._run(jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]])
        self.assertEqual(client.get(url).json()["preparation"]["state"], "complete")

    def test_missing_file_resume_preserves_variant_revision_and_backend(self):
        state = self.begin()
        self.transfer(state)
        jobs._run(jobs.JOBS[state["cardId"]], jobs.CANCEL[state["cardId"]])
        card = registry.read_llm_registry()["cards"][0]
        Path(card["localMetadata"]["files"][0]).unlink()
        jobs.start_model_runtime(state["cardId"])
        with patch.object(runtime, "selected_backend", return_value="cuda"):
            jobs._resume_model(jobs.JOBS[state["cardId"]])
        current = list(hf.HF_DOWNLOADS.values())[-1]
        self.assertNotEqual(current["id"], state["id"])
        metadata = registry.read_llm_registry()["cards"][0]["localMetadata"]
        self.assertEqual((metadata["variant"], metadata["revision"], metadata["backend"]), ("model-Q4", "fixed", "cpu"))
        self.transfer(current)
        hf._model_info_with_optional_token.assert_called_with(unittest.mock.ANY, "org/model", revision="fixed", files_metadata=True)

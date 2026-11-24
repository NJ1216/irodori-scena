from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import inference, llm_model_tests, llm_registry, local_llm_runtime, mtp_assets


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class LlmModelTestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selected = {"provider": "openai", "baseUrl": "https://example.invalid/v1", "model": "test-model",
                         "apiKey": "secret", "cardId": "card", "source": "remote", "localMetadata": None,
                         "settings": {}}
        llm_model_tests.MODEL_TESTS.clear()
        llm_model_tests.MODEL_TEST_CANCEL.clear()

    def _run(self, response: dict[str, object]) -> tuple[dict[str, object], list[dict[str, object]]]:
        job: dict[str, object] = {"cardId": "card", "state": "queued", "stage": "queued"}
        statuses: list[dict[str, object]] = []
        with (
            patch.object(llm_registry, "resolve_llm_card", return_value=dict(self.selected)),
            patch.object(local_llm_runtime, "local_llm_status", return_value={"model": None}),
            patch.object(inference, "shutdown_inference_worker"),
            patch.object(local_llm_runtime, "unload_local_llm"),
            patch.object(llm_registry, "set_llm_test_status", side_effect=lambda _id, value: statuses.append(value)),
            patch.object(llm_model_tests.urllib.request, "urlopen", return_value=_Response(response)),
        ):
            llm_model_tests._run_test(job, threading.Event())
        return job, statuses

    def test_success_requires_non_empty_chat_completion(self) -> None:
        job, statuses = self._run({"choices": [{"message": {"content": "ok"}}]})
        self.assertEqual(job["state"], "passed")
        self.assertEqual(statuses[-1]["state"], "passed")

    def test_empty_response_has_its_own_category(self) -> None:
        job, statuses = self._run({"choices": [{"message": {"content": ""}}]})
        self.assertEqual(job["errorCategory"], "empty_response")
        self.assertEqual(statuses[-1]["state"], "failed")

    def test_thinking_disabled_is_sent_to_openai_compatible_probe(self) -> None:
        self.selected.update(provider="scena-local", settings={"thinking": False})
        response = _Response({"choices": [{"message": {"content": "接続確認済み"}}]})
        with patch.object(llm_model_tests.urllib.request, "urlopen", return_value=response) as opening:
            result = llm_model_tests._completion(self.selected, threading.Event())
        request = opening.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(result, "接続確認済み")
        self.assertEqual(payload["reasoning_effort"], "none")

    def test_thinking_enabled_does_not_disable_reasoning(self) -> None:
        self.selected.update(provider="scena-local", settings={"thinking": True})
        response = _Response({"choices": [{"message": {"content": "ok"}}]})
        with patch.object(llm_model_tests.urllib.request, "urlopen", return_value=response) as opening:
            llm_model_tests._completion(self.selected, threading.Event())
        payload = json.loads(opening.call_args.args[0].data.decode("utf-8"))
        self.assertNotIn("reasoning_effort", payload)

    def test_cancel_restores_untested_status(self) -> None:
        job: dict[str, object] = {"cardId": "card", "state": "queued", "stage": "queued"}
        cancel = threading.Event()
        cancel.set()
        with (
            patch.object(llm_registry, "resolve_llm_card", return_value=dict(self.selected)),
            patch.object(local_llm_runtime, "local_llm_status", return_value={"model": None}),
            patch.object(local_llm_runtime, "unload_local_llm"),
            patch.object(llm_registry, "set_llm_test_status") as status,
        ):
            llm_model_tests._run_test(job, cancel)
        self.assertEqual(job["state"], "cancelled")
        self.assertEqual(status.call_args.args[1]["state"], "untested")

    def test_failure_classifier_distinguishes_timeout_and_memory_guard(self) -> None:
        self.assertEqual(llm_model_tests._failure_category(TimeoutError("timed out")), "timeout")
        self.assertEqual(llm_model_tests._failure_category(RuntimeError("memory guard rejected load")), "memory_guard")
        self.assertEqual(llm_model_tests._failure_category(RuntimeError("Metal out of memory")), "metal_oom")

    def test_local_capabilities_are_read_from_nested_text_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "config.json").write_text(json.dumps({
                "model_type": "gemma4",
                "text_config": {"max_position_embeddings": 262144},
                "vision_config": {"max_position_embeddings": 131072},
            }), encoding="utf-8")
            selected = {"source": "managed", "localMetadata": {"path": str(path)}}
            capabilities = llm_model_tests._local_model_capabilities(selected)
        self.assertEqual(capabilities["inputTokenLimit"], 262144)
        self.assertEqual(capabilities["outputTokenLimit"], 262144)
        self.assertEqual(capabilities["source"], "model-config")

    def test_mtp_requires_attached_drafter_not_fail_soft_fallback(self) -> None:
        self.selected.update(provider="scena-local", source="managed", settings={"mtp": True},
                             localMetadata={"path": "/tmp/model"})
        expected = "/tmp/assistant"
        with (
            patch.object(llm_model_tests, "_static_inspection"),
            patch.object(local_llm_runtime, "load_local_llm"),
            patch.object(local_llm_runtime, "local_llm_runtime_endpoint", return_value="http://127.0.0.1/v1"),
            patch.object(local_llm_runtime, "local_llm_runtime_api_key", return_value="key"),
            patch("server.modules.local_llm_metrics.local_llm_engine_status", return_value={
                "model": "test-model", "mtpActive": False, "mtpDraftModel": expected,
            }),
            patch.object(mtp_assets, "resolve_mtp_draft", return_value=Path(expected)),
        ):
            job, _ = self._run({"choices": [{"message": {"content": "ok"}}]})
        self.assertEqual(job["state"], "failed")
        self.assertIn("fallback", str(job["error"]))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import scena_test_isolation  # noqa: F401
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import server.app  # noqa: F401
from server.modules import llama_cpp_server, local_llm_runtime


class LlamaCppServerTests(unittest.TestCase):
    def test_command_is_loopback_authenticated_and_webui_disabled(self):
        with patch("server.modules.llama_cpp_runtime.llama_cpp_runtime_status", return_value={
            "ready": True, "path": "C:/runtime", "version": "test", "backend": "cuda"
        }), patch.object(llama_cpp_server, "model_files", return_value=[Path("C:/models/model.gguf")]), \
                patch("server.modules.constants.LOCAL_LLM_ROOT", Path("/tmp/scena-test")):
            command, log = llama_cpp_server.command("model", 43210, "secret", "cuda", 32768)
            log.close()
        self.assertIn("127.0.0.1", command)
        self.assertIn("secret", command)
        self.assertIn("--no-webui", command)
        self.assertEqual(command[command.index("--ctx-size") + 1], "32768")
        self.assertEqual(command[command.index("--fit") + 1], "on")
        self.assertEqual(command[command.index("--fit-target") + 1], "2048")
        self.assertNotIn("--n-gpu-layers", command)

    def test_switching_model_terminates_owned_server_and_rotates_key(self):
        first, second = Mock(), Mock()
        for process in (first, second):
            process.poll.return_value = None
            process.wait.return_value = 0
        spawned = iter([first, second])
        with patch.object(local_llm_runtime.platform, "system", return_value="Windows"), \
                patch("server.modules.llama_cpp_runtime.selected_backend", return_value="cpu"), \
                patch("server.modules.llama_cpp_runtime.llama_cpp_runtime_status", return_value={
                    "ready": True, "path": "C:/runtime", "version": "test", "backend": "cpu", "job": {"state": "idle"}
                }), patch.object(llama_cpp_server, "spawn", side_effect=lambda *_args: next(spawned)), \
                patch.object(local_llm_runtime, "_select_runtime_port", side_effect=[43101, 43102]), \
                patch.object(local_llm_runtime, "_runtime_health", return_value=True), \
                patch.object(local_llm_runtime, "_llama_runtime_context", return_value=32768), \
                patch("server.modules.resource_coordinator.acquire_llm_memory"), \
                patch("server.modules.resource_coordinator.release_memory"), \
                patch.object(local_llm_runtime, "RUNTIME_PROCESS", None), \
                patch.object(local_llm_runtime, "LOADED_MODEL", None), \
                patch.object(local_llm_runtime, "RUNTIME_API_KEY", ""):
            local_llm_runtime.load_local_llm("one")
            first_key = local_llm_runtime.RUNTIME_API_KEY
            local_llm_runtime.load_local_llm("two")
            second_key = local_llm_runtime.RUNTIME_API_KEY
            local_llm_runtime.stop_local_llm()
        first.terminate.assert_called_once()
        second.terminate.assert_called_once()
        self.assertNotEqual(first_key, second_key)

    def test_stop_kills_server_after_timeout(self):
        process = Mock()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("llama", 5), 0]
        with patch.object(local_llm_runtime, "RUNTIME_PROCESS", process), \
                patch("server.modules.resource_coordinator.release_memory"):
            local_llm_runtime.stop_local_llm()
        process.kill.assert_called_once()

    def test_context_memory_failure_retries_at_next_tier_only(self):
        first, second = Mock(), Mock()
        first.poll.return_value = 1
        second.poll.return_value = None
        second.wait.return_value = 0
        candidates = []
        with patch.object(local_llm_runtime.platform, "system", return_value="Windows"), \
                patch("server.modules.llama_cpp_runtime.selected_backend", return_value="cpu"), \
                patch("server.modules.llama_cpp_runtime.llama_cpp_runtime_status", return_value={
                    "ready": True, "path": "C:/runtime", "version": "test", "backend": "cpu", "job": {"state": "idle"}
                }), patch("server.modules.llm_registry.read_llm_registry", return_value={"cards": [{
                    "modelId": "model", "localMetadata": {"diskBytes": 1, "modelContextLimit": 32768},
                }]}), patch("server.modules.llama_cpp_context.available_memory_bytes", return_value=20 * 1024**3), \
                patch("server.modules.llama_cpp_context.select_context_size", return_value=32768), \
                patch.object(llama_cpp_server, "spawn", side_effect=lambda *_args: candidates.append(_args[-1]) or (first if len(candidates) == 1 else second)), \
                patch.object(local_llm_runtime, "_select_runtime_port", side_effect=[43101, 43102]), \
                patch.object(local_llm_runtime, "_runtime_health", return_value=True), \
                patch.object(local_llm_runtime, "_llama_runtime_context", return_value=16384), \
                patch.object(local_llm_runtime, "_llama_start_failure_category", return_value="context_memory"), \
                patch("server.modules.resource_coordinator.acquire_llm_memory"), \
                patch("server.modules.resource_coordinator.release_memory"), \
                patch.object(local_llm_runtime, "RUNTIME_PROCESS", None), \
                patch.object(local_llm_runtime, "LOADED_MODEL", None):
            status = local_llm_runtime.load_local_llm("model")
            local_llm_runtime.stop_local_llm()
        self.assertEqual(candidates, [32768, 16384])
        self.assertEqual(status["contextSize"], 16384)

    def test_non_memory_start_failure_is_not_retried(self):
        process = Mock()
        process.poll.return_value = 1
        calls = []
        with patch.object(local_llm_runtime.platform, "system", return_value="Windows"), \
                patch("server.modules.llama_cpp_runtime.selected_backend", return_value="cpu"), \
                patch("server.modules.llama_cpp_runtime.llama_cpp_runtime_status", return_value={
                    "ready": True, "path": "C:/runtime", "version": "test", "backend": "cpu", "job": {"state": "idle"}
                }), patch("server.modules.llm_registry.read_llm_registry", return_value={"cards": []}), \
                patch("server.modules.llama_cpp_context.available_memory_bytes", return_value=None), \
                patch("server.modules.llama_cpp_context.select_context_size", return_value=32768), \
                patch.object(llama_cpp_server, "spawn", side_effect=lambda *_args: calls.append(_args[-1]) or process), \
                patch.object(local_llm_runtime, "_select_runtime_port", return_value=43101), \
                patch.object(local_llm_runtime, "_llama_start_failure_category", return_value="model"), \
                patch("server.modules.resource_coordinator.release_memory"), \
                patch.object(local_llm_runtime, "RUNTIME_PROCESS", None), \
                patch.object(local_llm_runtime, "LOADED_MODEL", None):
            with self.assertRaisesRegex(Exception, "起動直後"):
                local_llm_runtime.load_local_llm("model")
        self.assertEqual(calls, [32768])

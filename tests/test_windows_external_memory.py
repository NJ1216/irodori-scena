from __future__ import annotations
import scena_test_isolation  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from server import app as _app  # noqa: F401
from server.modules import windows_external_memory as memory
from server.modules.ollama_native import ollama_native_completion
from server.modules.lmstudio_native import lmstudio_json_completion, lmstudio_stream_text_completion


def request(provider: str = "ollama") -> SimpleNamespace:
    return SimpleNamespace(provider=provider, base_url="http://127.0.0.1:11434/v1", model="model-a", api_key="")


class WindowsExternalMemoryTests(unittest.TestCase):
    def tearDown(self) -> None:
        memory._OWNED_MODELS.clear()

    def test_native_provider_entry_points_are_guarded(self) -> None:
        self.assertTrue(hasattr(ollama_native_completion, "__wrapped__"))
        self.assertTrue(hasattr(lmstudio_json_completion, "__wrapped__"))
        self.assertTrue(hasattr(lmstudio_stream_text_completion, "__wrapped__"))

    def test_darwin_does_not_change_external_llm_lifecycle(self) -> None:
        called = []
        wrapped = memory.windows_accelerator_handoff(lambda value: called.append(value.model) or "ok")
        with (
            patch.object(memory, "_is_windows_local", return_value=False),
            patch("server.modules.resource_coordinator.acquire_llm_memory") as acquire,
        ):
            self.assertEqual(wrapped(request()), "ok")
        acquire.assert_not_called()
        self.assertEqual(called, ["model-a"])

    def test_windows_stops_tts_and_tracks_only_a_model_loaded_by_scena(self) -> None:
        wrapped = memory.windows_accelerator_handoff(lambda _value: "ok")
        with (
            patch.object(memory, "_is_windows_local", return_value=True),
            patch.object(memory, "_loaded", side_effect=[False, True]),
            patch("server.modules.resource_coordinator.acquire_llm_memory") as acquire,
        ):
            self.assertEqual(wrapped(request()), "ok")
        acquire.assert_called_once()
        self.assertEqual(next(iter(memory._OWNED_MODELS.values()))["model"], "model-a")

    def test_windows_does_not_claim_a_preloaded_user_model(self) -> None:
        wrapped = memory.windows_accelerator_handoff(lambda _value: "ok")
        with (
            patch.object(memory, "_is_windows_local", return_value=True),
            patch.object(memory, "_loaded", return_value=True),
            patch("server.modules.resource_coordinator.acquire_llm_memory"),
        ):
            wrapped(request())
        self.assertFalse(memory._OWNED_MODELS)

    def test_tts_handoff_unloads_owned_ollama_model(self) -> None:
        memory._remember(request())
        with patch.object(memory.sys, "platform", "win32"), patch.object(memory, "_post") as post:
            memory.release_windows_external_llm()
        self.assertTrue(post.call_args.args[0].endswith("/api/generate"))
        self.assertEqual(post.call_args.args[2], {"model": "model-a", "keep_alive": 0})
        self.assertFalse(memory._OWNED_MODELS)

    def test_tts_handoff_unloads_only_owned_lmstudio_instances(self) -> None:
        memory._remember(request("lmstudio"))
        with (
            patch.object(memory.sys, "platform", "win32"),
            patch.object(memory, "_lmstudio_instances", return_value=["scena-instance"]),
            patch.object(memory, "_post") as post,
        ):
            memory.release_windows_external_llm()
        self.assertTrue(post.call_args.args[0].endswith("/api/v1/models/unload"))
        self.assertEqual(post.call_args.args[2], {"instance_id": "scena-instance"})


if __name__ == "__main__":
    unittest.main()

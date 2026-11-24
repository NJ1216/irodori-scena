from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules.llm_client import _completion_options
from server.modules.llm_sampling import resolve_sampling_settings


SETTINGS = {
    "temperature": 0.35,
    "topP": 0.9,
    "topK": 40,
    "minP": 0.05,
    "repetitionPenalty": 1.1,
}


class LlmSamplingTests(unittest.TestCase):
    def request(self, provider: str) -> SimpleNamespace:
        return SimpleNamespace(provider=provider, base_url="http://localhost/v1", model="model")

    def test_local_providers_keep_every_supported_card_setting(self) -> None:
        expected = {
            "temperature": 0.35, "top_p": 0.9, "top_k": 40,
            "min_p": 0.05, "repeat_penalty": 1.1,
        }
        for provider in ("scena-local", "ollama", "lmstudio"):
            with self.subTest(provider=provider), patch(
                "server.modules.llm_registry.resolve_llm_settings", return_value=SETTINGS
            ):
                self.assertEqual(resolve_sampling_settings(self.request(provider), 0.7), expected)

    def test_openai_compatible_only_keeps_temperature_and_top_p(self) -> None:
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value=SETTINGS):
            self.assertEqual(
                resolve_sampling_settings(self.request("openai"), 0.7),
                {"temperature": 0.35, "top_p": 0.9},
            )

    def test_deterministic_policy_ignores_every_card_override(self) -> None:
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value=SETTINGS) as resolve:
            self.assertEqual(
                resolve_sampling_settings(self.request("ollama"), 0.1, "deterministic"),
                {"temperature": 0.1},
            )
        resolve.assert_not_called()

    def test_creative_policy_falls_back_to_the_feature_temperature(self) -> None:
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value={}):
            self.assertEqual(
                resolve_sampling_settings(self.request("ollama"), 0.55),
                {"temperature": 0.55},
            )

    def test_scena_local_disables_reasoning_when_thinking_is_off(self) -> None:
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value={"thinking": False}):
            self.assertEqual(
                _completion_options(self.request("scena-local")),
                {"reasoning_effort": "none"},
            )

    def test_scena_local_keeps_reasoning_when_thinking_is_on(self) -> None:
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value={"thinking": True}):
            self.assertEqual(_completion_options(self.request("scena-local")), {})


if __name__ == "__main__":
    unittest.main()

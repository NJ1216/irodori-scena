from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import draft_capability, llm_catalog, llm_registry, llm_registry_metadata, models


class LlmCatalogTests(unittest.TestCase):
    url = "https://generativelanguage.googleapis.com/v1beta/openai"

    def test_catalog_is_exact_unique_and_sourced_for_seven_families(self):
        identities = set()
        families = set()
        for family, ids, context, output, source in llm_catalog.CATALOG:
            families.add(family)
            self.assertTrue(source.startswith("https://"))
            self.assertGreater(context, 0)
            self.assertTrue(output is None or output > 0)
            for model in ids:
                self.assertNotIn((family, model), identities)
                identities.add((family, model))
                self.assertIsNotNone(llm_catalog.catalog_entry(family, model))
        self.assertEqual(len(families), 7)

    def test_gemini_prefix_and_partial_api_values_preserve_schema_and_original(self):
        original = {"inputTokenLimit": 32768, "source": "provider-api",
                    "structuredOutput": {"streaming": {"state": "unsupported"}}}
        snapshot = copy.deepcopy(original)
        result = llm_catalog.effective_capabilities("openai", self.url, "models/gemini-3.5-flash", original)
        self.assertEqual(result["inputTokenLimit"], 32768)
        self.assertEqual(result["outputTokenLimit"], 65536)
        self.assertEqual(result["catalog"]["fields"], ["outputTokenLimit"])
        self.assertEqual(result["source"], "provider-api")
        self.assertEqual(result["structuredOutput"], original["structuredOutput"])
        self.assertEqual(original, snapshot)

    def test_unknown_local_proxy_and_wrong_path_are_not_guessed(self):
        for provider, url, model in (
            ("ollama", self.url, "gemini-3.5-flash"),
            ("openai", "http://localhost:8000/v1", "gemini-3.5-flash"),
            ("openai", self.url + "/proxy", "gemini-3.5-flash"),
            ("openai", self.url.replace(".com", ".com.evil.test"), "gemini-3.5-flash"),
            ("openai", self.url, "gemini-3.5-flash-custom"),
            ("openai", self.url, "gemini-3-pro-preview"),
        ):
            with self.subTest(provider=provider, url=url, model=model):
                self.assertEqual(llm_catalog.effective_capabilities(provider, url, model, {}), {})

    def test_unknown_output_is_not_confused_with_default_output(self):
        result = llm_catalog.effective_capabilities("openai", "https://api.moonshot.ai/v1", "kimi-k3", {})
        self.assertEqual(result["inputTokenLimit"], 1000000)
        self.assertNotIn("outputTokenLimit", result)

    def test_measured_limits_win_and_invalid_limits_are_filled(self):
        caps = {"inputTokenLimit": 4096, "outputTokenLimit": 2048, "source": "user"}
        self.assertEqual(llm_catalog.effective_capabilities("openai", self.url, "gemini-3.5-flash", caps), caps)
        for invalid in (None, True, 0, -1, "65536"):
            result = llm_catalog.effective_capabilities("openai", self.url, "gemini-3.5-flash",
                                                        {"outputTokenLimit": invalid})
            self.assertEqual(result["outputTokenLimit"], 65536)

    def test_generation_capability_resolver_uses_catalog_without_registry_writes(self):
        with patch.object(llm_registry, "read_llm_registry", return_value={"endpoints": [], "cards": []}), \
             patch.object(llm_registry, "write_llm_registry") as write:
            result = llm_registry_metadata.resolve_llm_capabilities("openai", self.url, "models/gemini-3.5-flash")
        self.assertEqual((result["inputTokenLimit"], result["outputTokenLimit"]), (1048576, 65536))
        write.assert_not_called()

    def test_long_draft_plan_respects_catalog_output_ceiling(self):
        request = models.DraftRequest(base_url=self.url, model="models/gemini-3.5-flash",
                                      character_ids=["a"], target_minutes=60, theme="自己紹介")
        with patch.object(llm_registry, "read_llm_registry", return_value={"endpoints": [], "cards": []}), \
             patch.object(draft_capability, "local_memory_gib", return_value=16), \
             patch.object(draft_capability, "local_hardware_name", return_value="test"):
            profile = draft_capability.build_draft_capability_profile(request, adaptive_long_form=True)
        self.assertEqual(profile["providerOutputTokenLimit"], 65536)
        self.assertLessEqual(profile["outputTokenLimit"], 65536)
        self.assertLessEqual(profile["effectiveContext"], 1048576)
        self.assertEqual(request.model, "models/gemini-3.5-flash")

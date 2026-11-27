from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import patch

from server.app import (
    AiDirectionRequest, DraftRequest, build_direction_capability_profile,
    build_draft_capability_profile, dialogue_output_token_budget, reduce_ollama_context,
    prepare_draft_llm_call, select_direction_context,
)


def ollama_request() -> DraftRequest:
    return DraftRequest(
        provider="ollama",
        base_url="http://127.0.0.1:11434/v1",
        model="local-test",
        character_ids=["cast-a"],
        target_minutes=2,
        theme="雨の日の帰り道で、二人が小さな約束をする。",
    )


class LlmCapabilityProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = patch("server.modules.llm_registry.resolve_llm_settings", return_value={})
        load = patch("server.modules.ollama_context.load_ollama_allocation", return_value=32768)
        settings.start()
        load.start()
        self.addCleanup(settings.stop)
        self.addCleanup(load.stop)
    def tearDown(self) -> None:
        from server.registry import deps
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = None

    def test_resolved_default_provider_drives_draft_capability(self) -> None:
        initial = ollama_request().model_copy(update={"provider": "openai"})
        logical = ollama_request()
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=64),
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(32768, 16384, None)),
            patch("server.modules.local_llm_runtime.resolve_logical_llm_request", return_value=logical),
        ):
            profile = build_draft_capability_profile(initial)
        self.assertEqual(profile["provider"], "ollama")
        self.assertEqual(profile["contextCeiling"], 16384)

    def test_exact_call_budget_satisfies_context_equation_and_pins_dialogue_tier(self) -> None:
        from server.registry import deps
        deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile = {
            "provider": "ollama", "contextCeiling": 8192, "effectiveContext": 8192,
        }
        first = prepare_draft_llm_call(
            ollama_request(), system="固定" * 700, user={"chapter": "本文" * 300},
            max_tokens=6144, feature="draft-dialogue",
        )
        profile = deps.DRAFT_LLM_THREAD_CONTEXT.capability_profile
        self.assertLess(first, 6144)
        self.assertLessEqual(
            profile["actualPromptTokenEstimate"] + first + 1024, profile["dialogueContext"]
        )
        prepare_draft_llm_call(
            ollama_request(), system="固定" * 600, user={"chapter": "本文" * 200},
            max_tokens=2000, feature="draft-dialogue",
        )
        self.assertEqual(profile["effectiveContext"], profile["dialogueContext"])
    def test_direction_ollama_uses_product_default_without_benchmark_evidence(self) -> None:
        request = AiDirectionRequest(provider="ollama", base_url="http://127.0.0.1:11434/v1",
                                     model="local-test", line_ids=["line-1"])
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=128),
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(131072, None, None)),
        ):
            profile = build_direction_capability_profile(request)
        self.assertEqual(profile["directionChunkSize"], 30)
        self.assertEqual(profile["directionChunkCapacity"], 30)
        self.assertEqual(profile["contextCeiling"], 32768)
        self.assertEqual(select_direction_context(profile, input_tokens=3000, output_tokens=2000), 8192)

    def test_ollama_cloud_direction_does_not_require_local_runtime_allocation(self) -> None:
        request = AiDirectionRequest(provider="ollama", base_url="http://127.0.0.1:11434/v1",
                                     model="gemma4:31b-cloud", line_ids=["line-1"])
        with (
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(None, None, None)),
            patch("server.modules.ollama_context.load_ollama_allocation") as load,
        ):
            profile = build_direction_capability_profile(request)
        load.assert_not_called()
        self.assertTrue(profile["remoteCloud"])
        self.assertIsNone(profile["contextCeiling"])
        self.assertEqual(profile["directionChunkSize"], 30)

    def test_generic_openai_direction_starts_at_thirty_without_context_setting(self) -> None:
        request = AiDirectionRequest(provider="openai", base_url="https://example.invalid/v1",
                                     model="remote", line_ids=["line-1"])
        profile = build_direction_capability_profile(request)
        self.assertEqual(profile["directionChunkSize"], 30)
        self.assertIsNone(profile["effectiveContext"])

    def test_known_direction_context_caps_chunk_before_calling(self) -> None:
        request = AiDirectionRequest(provider="ollama", base_url="http://127.0.0.1:11434/v1",
                                     model="local-test", line_ids=["line-1"])
        for context, expected in ((32768, 30), (16384, 20), (8192, 10)):
            with self.subTest(context=context), \
                patch("server.modules.draft_capability.local_memory_gib", return_value=128), \
                patch("server.modules.draft_capability.ollama_runtime_details",
                      return_value=(context, None, None)):
                self.assertEqual(build_direction_capability_profile(request)["directionChunkSize"], expected)

    def test_direction_capacity_rejection_reduces_context_and_chunk_together(self) -> None:
        profile = {"provider": "lmstudio", "effectiveContext": 32768, "contextCeiling": 32768,
                   "directionChunkSize": 30, "fallbackReason": ""}
        self.assertFalse(reduce_ollama_context(profile, "insufficient memory for context_length"))
        self.assertEqual((profile["effectiveContext"], profile["directionChunkSize"]), (16384, 20))
        self.assertTrue(profile["retryDirectionChunk"])

    def test_short_ollama_draft_respects_allocated_context(self) -> None:
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=128),
            patch("server.modules.draft_capability.local_hardware_name", return_value="Apple M4 Max"),
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(65536, None, None)),
        ):
            profile = build_draft_capability_profile(ollama_request())
        self.assertEqual(profile["contextCeiling"], 32768)
        self.assertEqual(profile["effectiveContext"], 32768)
        self.assertEqual(profile["predictedCalls"], 1)
        self.assertEqual(profile["estimatedResentTokens"], 0)
        self.assertEqual(profile["hardwareName"], "Apple M4 Max")

    def test_capability_profile_allows_missing_hardware_details(self) -> None:
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=None),
            patch("server.modules.draft_capability.local_hardware_name", return_value=None),
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(8192, None, None)),
        ):
            profile = build_draft_capability_profile(ollama_request())
        self.assertIsNone(profile["detectedMemoryGiB"])
        self.assertIsNone(profile["hardwareName"])
        self.assertEqual(profile["effectiveContext"], 8192)

    def test_running_ollama_context_is_used_when_memory_probe_is_unavailable(self) -> None:
        request = ollama_request().model_copy(update={"target_minutes": 15})
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=None),
            patch("server.modules.draft_capability.local_hardware_name", return_value=None),
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(32768, 32768, None)),
        ):
            profile = build_draft_capability_profile(request, adaptive_long_form=True)
        self.assertEqual(profile["contextCeiling"], 32768)
        self.assertEqual(profile["effectiveContext"], 32768)
        self.assertGreater(profile["outputTokenLimit"], 2048)

    def test_ollama_allocation_is_independent_of_host_memory_heuristic(self) -> None:
        cases = [(64, 65536, 32768), (32, 65536, 32768), (128, 8192, 8192)]
        for memory, model_limit, ceiling in cases:
            with self.subTest(memory=memory, model_limit=model_limit), \
                patch("server.modules.draft_capability.local_memory_gib", return_value=memory), \
                patch("server.modules.draft_capability.ollama_runtime_details", return_value=(model_limit, None, None)):
                profile = build_draft_capability_profile(ollama_request())
                self.assertEqual(profile["contextCeiling"], ceiling)
                self.assertLessEqual(profile["effectiveContext"], ceiling)

    def test_long_ollama_job_reserves_output_within_actual_allocation(self) -> None:
        request = ollama_request().model_copy(update={"target_minutes": 60})
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=128),
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(65536, None, None)),
        ):
            profile = build_draft_capability_profile(request)
        self.assertEqual(profile["effectiveContext"], 32768)
        self.assertEqual(profile["outputTokenLimit"], 30720)
        self.assertGreater(profile["predictedCalls"], 1)

    def test_adaptive_long_jobs_expand_output_with_context_and_minimize_calls(self) -> None:
        expected = {5: (32768, 30720, 1), 30: (32768, 30720, 2), 60: (32768, 30720, 3)}
        for minutes, values in expected.items():
            request = ollama_request().model_copy(update={"target_minutes": minutes})
            with self.subTest(minutes=minutes), \
                patch("server.modules.draft_capability.local_memory_gib", return_value=128), \
                patch("server.modules.draft_capability.ollama_runtime_details",
                      return_value=(65536, None, None)):
                profile = build_draft_capability_profile(request, adaptive_long_form=True)
            self.assertEqual((profile["effectiveContext"], profile["outputTokenLimit"],
                              profile["predictedCalls"]), values)
            self.assertLessEqual(profile["promptTokenEstimate"] + profile["outputTokenLimit"] + 1024,
                                 profile["effectiveContext"])

    def test_missing_detail_uses_verified_preload_allocation(self) -> None:
        with (
            patch("server.modules.draft_capability.local_memory_gib", return_value=128),
            patch("server.modules.draft_capability.ollama_runtime_details", return_value=(None, None, "取得失敗")),
        ):
            profile = build_draft_capability_profile(ollama_request())
        self.assertEqual(profile["effectiveContext"], 32768)
        self.assertIn("取得失敗", profile["fallbackReason"])

    def test_dialogue_budget_matches_character_conversion_and_profile_cap(self) -> None:
        self.assertEqual(dialogue_output_token_budget(5000, 30000), 6144)
        self.assertEqual(dialogue_output_token_budget(5000, 4096), 4096)
        self.assertGreater(dialogue_output_token_budget(10000, 30000, dynamic_output=True), 6144)

    def test_non_ollama_keeps_compatible_limits(self) -> None:
        request = ollama_request().model_copy(update={"provider": "openai"})
        profile = build_draft_capability_profile(request)
        self.assertEqual((profile["outputTokenLimit"], profile["maxChunkCharacters"]), (8192, 2500))

    def test_openai_card_context_sizes_integrated_records_without_exposing_context(self) -> None:
        request = ollama_request().model_copy(update={"provider": "openai"})
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value={"contextLimit": 16384}):
            profile = build_draft_capability_profile(request)
        self.assertEqual(profile["contextCeiling"], 16384)
        self.assertFalse(profile["contextApplied"])
        self.assertEqual(profile["maxChunkCharacters"], 2160)
        self.assertLessEqual(profile["outputTokenLimit"], 6144)

    def test_huge_openai_context_never_raises_product_quality_limits(self) -> None:
        request = ollama_request().model_copy(update={"provider": "openai"})
        for context_limit in (131072, 1048576):
            with self.subTest(context_limit=context_limit), patch(
                "server.modules.llm_registry.resolve_llm_settings", return_value={"contextLimit": context_limit}
            ):
                profile = build_draft_capability_profile(request)
            self.assertEqual(profile["maxChunkCharacters"], 2160)
            self.assertLessEqual(profile["outputTokenLimit"], 6144)

    def test_adaptive_external_uses_discovered_output_limit(self) -> None:
        request = ollama_request().model_copy(update={"provider": "openai", "target_minutes": 30})
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value={"contextLimit": None}), \
             patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value={
                 "inputTokenLimit": 131072, "outputTokenLimit": 16384,
             }):
            profile = build_draft_capability_profile(request, adaptive_long_form=True)
        self.assertEqual(profile["providerOutputTokenLimit"], 16384)
        self.assertLessEqual(profile["outputTokenLimit"], 16384)
        self.assertGreater(profile["outputTokenLimit"], 6144)
        self.assertLessEqual(profile["promptTokenEstimate"] + profile["outputTokenLimit"] + 1024,
                             profile["effectiveContext"])

    def test_adaptive_external_without_metadata_sizes_output_from_duration(self) -> None:
        request = ollama_request().model_copy(update={"provider": "openai", "target_minutes": 30})
        with patch("server.modules.llm_registry.resolve_llm_settings", return_value={"contextLimit": None}), \
             patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value={}):
            profile = build_draft_capability_profile(request, adaptive_long_form=True)
        self.assertIsNone(profile["effectiveContext"])
        self.assertGreater(profile["outputTokenLimit"], 6144)
        self.assertEqual(profile["predictedCalls"], 1)

    def test_rejected_num_ctx_halves_until_4k(self) -> None:
        profile = {"provider": "ollama", "effectiveContext": 32768, "promptTokenEstimate": 1024}
        self.assertTrue(reduce_ollama_context(profile, "num_ctx context is too large"))
        self.assertEqual(profile["effectiveContext"], 16384)
        for _ in range(2):
            self.assertTrue(reduce_ollama_context(profile, "context rejected"))
        self.assertEqual(profile["effectiveContext"], 4096)
        self.assertFalse(reduce_ollama_context(profile, "context rejected"))

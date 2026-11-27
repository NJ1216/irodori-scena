from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest

from tools.direction_benchmark_core import (
    CACHE_SCENARIOS,
    CANDIDATES,
    assess_cache_records,
    cache_microbench_jobs,
    call_identity,
    latin_square_jobs,
    prompt_boundaries,
    production_score,
    reusable_blocks,
    score_response,
    summarize,
)
from tools.direction_benchmark_runtime import (
    append_jsonl,
    completed_identities,
    parse_pmset_low_power,
    wait_for_clean_thermal,
)


class DirectionBenchmarkTests(unittest.TestCase):
    def test_cache_matrix_covers_both_orders_cast_counts_and_repetitions(self) -> None:
        jobs = cache_microbench_jobs(3)
        self.assertEqual(len(jobs), 2 * 3 * 3 * len(CACHE_SCENARIOS))
        self.assertEqual(len({tuple(sorted(job.items())) for job in jobs}), len(jobs))

    def test_low_power_mode_uses_the_active_pmset_profile(self) -> None:
        custom = "Battery Power:\n lowpowermode 0\nAC Power:\n lowpowermode 1\n"
        self.assertTrue(parse_pmset_low_power(custom, "Now drawing from 'AC Power'"))
        self.assertFalse(parse_pmset_low_power(custom, "Now drawing from 'Battery Power'"))
        self.assertIsNone(parse_pmset_low_power(custom, "Unknown source"))

    def test_low_power_mode_accepts_current_macos_powermode_key(self) -> None:
        custom = "Battery Power:\n powermode 1\nAC Power:\n powermode 1\n"
        self.assertTrue(parse_pmset_low_power(custom, "Now drawing from 'AC Power'"))
        self.assertFalse(parse_pmset_low_power("AC Power:\n powermode 0\n", "Now drawing from 'AC Power'"))
        self.assertFalse(parse_pmset_low_power("AC Power:\n powermode 2\n", "Now drawing from 'AC Power'"))

    def test_thermal_wait_starts_immediately_when_initial_state_is_clean(self) -> None:
        sleeps = []
        result = wait_for_clean_thermal(
            None,
            read_state=lambda _: {"state": "nominal", "lowPowerMode": True},
            sleep=sleeps.append,
        )
        self.assertEqual(result["state"], "nominal")
        self.assertEqual(sleeps, [])

    def test_thermal_wait_requires_stable_recovery_after_dirty_state(self) -> None:
        states = iter([
            {"state": "serious", "lowPowerMode": True},
            {"state": "nominal", "lowPowerMode": True},
            {"state": "nominal", "lowPowerMode": True},
        ])
        observations = []
        sleeps = []
        result = wait_for_clean_thermal(
            None,
            poll_seconds=5,
            stable_samples=2,
            read_state=lambda _: next(states),
            observe=observations.append,
            sleep=sleeps.append,
        )
        self.assertEqual(result["state"], "nominal")
        self.assertEqual(sleeps, [5, 5])
        self.assertEqual(observations[-1]["consecutiveHealthySamples"], 2)

    def test_cache_assessment_requires_aligned_hot_tokens_and_zero_ssd_writes(self) -> None:
        result = assess_cache_records([{"identity": "a", "scenario": "exact-repeat", "metrics": {
            "cached_tokens": 2048, "cache_block_size": 1024, "ssd_saves": 0,
            "prefill_duration": 1.0, "hot_cache_evictions": 0,
        }}])
        self.assertTrue(result["allBlockAligned"])
        self.assertTrue(result["allSsdWritesZero"])

    def test_zero_cached_tokens_are_reported_without_block_alignment_failure(self) -> None:
        result = assess_cache_records([{"identity": "six-cast", "scenario": "exact-repeat", "metrics": {
            "cached_tokens": 0, "cache_block_size": 1024, "prefix_hits": 1, "ssd_saves": 0,
        }}])
        self.assertTrue(result["checks"][0]["prefixMatch"])
        self.assertFalse(result["checks"][0]["cacheUsed"])
        self.assertIsNone(result["checks"][0]["cachedTokenBlockAligned"])
        self.assertFalse(result["allBlockAligned"])

    def test_call_identity_is_stable_and_resume_uses_only_completed_rows(self) -> None:
        import tempfile
        from pathlib import Path

        identity = call_identity(suite="cache", prompt_order="production", cast_count=1, repetition=0,
                                 scenario="cold-first", fixture_id="f1", chunk_size=10, chunk_index=0)
        self.assertEqual(identity, call_identity(suite="cache", prompt_order="production", cast_count=1,
                                                repetition=0, scenario="cold-first", fixture_id="f1",
                                                chunk_size=10, chunk_index=0))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.jsonl"
            append_jsonl(path, {"identity": identity, "status": "thermal-contaminated"})
            append_jsonl(path, {"identity": "done", "status": "completed"})
            self.assertEqual(completed_identities(path), {"done"})

    def test_prompt_boundaries_report_1024_token_blocks(self) -> None:
        class Tokenizer:
            def encode(self, value, add_special_tokens=False):
                return list(range(len(value)))

            def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=False):
                return "".join(item["content"] for item in messages) + ("GEN" if add_generation_prompt else "")

        result = prompt_boundaries(Tokenizer(), "s" * 1100,
                                   {"request_settings": "x", "participating_casts": [], "lines": "line"})
        self.assertGreaterEqual(result["sectionEnds"]["lines"], result["sectionEnds"]["participating_casts"])
        self.assertEqual(reusable_blocks(3073), 3)

    def test_cache_first_prompt_preserves_settings_cast_lines_order(self) -> None:
        import server.app  # noqa: F401
        from server.modules.models import AiDirectionRequest
        from server.registry import deps

        request = AiDirectionRequest(model="test", line_ids=["line-1"], stage_direction=True)
        row = {"alias": "L1", "name": "A", "text": "台詞", "rate": None, "gap": None, "stage": ""}
        _, user = deps.build_direction_prompt(request, [row], [], [], [{"alias": "A"}],
                                              benchmark_prompt_order="cache-first")
        encoded = deps.canonical_prompt_json(user)
        self.assertLess(encoded.index("request_settings"), encoded.index("participating_casts"))
        self.assertLess(encoded.index("participating_casts"), encoded.index("lines"))
    def test_latin_square_balances_every_candidate_and_fixture(self) -> None:
        jobs = latin_square_jobs(30)
        self.assertEqual(len(jobs), 150)
        self.assertTrue(all(sum(job == (fixture, size) for job in jobs) == 1
                            for fixture in range(30) for size in CANDIDATES))

    def test_scorer_keeps_valid_siblings_and_reports_damage(self) -> None:
        score = score_response(
            "L1|rate=1.0|direction=静かに\nL1|gap=0.4\nL9|direction=不明\nL2|rate=速い|direction=笑顔😊（注）",
            ["L1", "L2"],
        )
        self.assertEqual(score["acceptedRows"], 2)
        self.assertEqual(score["duplicateAliases"], 1)
        self.assertEqual(score["ownershipErrors"], 1)
        self.assertEqual(score["prohibitedEmoji"], 1)
        self.assertEqual(score["invalidAnnotations"], 1)

    def test_production_scorer_uses_the_real_partial_patch_parser(self) -> None:
        import server.app  # noqa: F401
        from server.modules.models import AiDirectionRequest

        request = AiDirectionRequest(model="test", line_ids=["line-1"], emoji_expressions=True,
                                     speech_rate=True, stage_direction=True, allowed_emojis=["😊"])
        rows = [{"alias": "L1", "id": "line-1", "text": "おはよう", "stage": "", "rate": None,
                 "gap": None, "name": "A"}]
        score = production_score("L1|emoji=😊@おはよう|rate=0.9|direction=反響させずに", ["L1"], rows,
                                 request, {"😊"})
        self.assertEqual(score["acceptedByField"]["text"], 1)
        self.assertEqual(score["acceptedByField"]["speechRate"], 1)
        self.assertEqual(score["negativeCaptionRejections"], 1)

    def test_body_comparison_ignores_existing_and_inserted_expression_emoji(self) -> None:
        import server.app  # noqa: F401
        from server.modules.models import AiDirectionRequest

        request = AiDirectionRequest(model="test", line_ids=["line-1"], emoji_expressions=True,
                                     overwrite_existing=True, allowed_emojis=["😊"])
        rows = [{"alias": "L1", "id": "line-1", "text": "😌おはよう", "stage": "", "rate": None,
                 "gap": None, "name": "A"}]
        score = production_score("L1|emoji=😊@おはよう", ["L1"], rows, request, {"😊"})
        self.assertEqual(score["bodyModifications"], 0)

    def test_aggregation_deduplicates_thermal_retry_identity(self) -> None:
        from tools.direction_benchmark_core import aggregate_call_records

        score = {"expectedRows": 1, "acceptedRows": 1, "missingRows": 0, "duplicateAliases": 0,
                 "ownershipErrors": 0, "acceptedFields": 1, "prohibitedEmoji": 0,
                 "invalidAnnotations": 0}
        calls = [{"identity": "same", "suite": "exploration", "fixtureId": "f", "chunkSize": 30,
                  "status": status, "wallSeconds": wall, "score": score, "metrics": {}}
                 for status, wall in (("thermal-contaminated", 99), ("completed", 10))]
        result = aggregate_call_records(calls)[0]
        self.assertEqual((result["calls"], result["wallSeconds"], result["qualityCallCount"]), (1, 10, 1))

    def test_summary_uses_whole_fixture_time(self) -> None:
        rows = [{"chunkSize": 10, "status": "completed", "wallSeconds": value, "calls": 10,
                 "score": {"ownershipErrors": 0, "missingRows": 0, "duplicateAliases": 0,
                           "prohibitedEmoji": 0, "invalidAnnotations": 0, "validFields": 400,
                           "expectedRows": 100, "acceptedRows": 100}, "metrics": {}} for value in (10, 12, 20)]
        result = summarize(rows)[0]
        self.assertEqual(result["medianSeconds"], 12)
        self.assertEqual(result["p95Seconds"], 20)
        self.assertEqual(result["calls"], 30)


if __name__ == "__main__":
    unittest.main()

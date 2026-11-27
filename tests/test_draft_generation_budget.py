from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import draft_packet_budget, draft_schedule, llm_transport, llm_retry_budget, runtime_state
from server.modules.draft_dialogue_job import DraftDialogueRun
from server.modules.draft_scoped_protocol import parse_scoped_dialogue
from server.modules.llm_session_usage import begin_llm_operation, record_llm_call, session_usage


class DraftGenerationBudgetTests(unittest.TestCase):
    def test_published_dialogue_progress_uses_accepted_characters(self):
        run = object.__new__(DraftDialogueRun)
        run.job_id, run.plan = "draft-progress", {}
        run.ending_source, run.completed, run.finalized_incomplete = "END", [], set()
        run.calls, run.call_limit = 1, 10
        run.processed, run.planned_targets, run.pending = set(), {"D1": 500, "END": 500}, [["D1", "END"]]
        run.developments = [["D1", "END"]]
        run.failed_calls = run.used_primary = run.used_reserve = 0
        run.used_coverage = run.used_recovery = run.used_ending = 0
        run.attempt_counts, run.partial_continuation = {}, False
        run.target = 1_000
        with (patch("server.modules.draft_job_state.update_draft_job"),
              patch("server.modules.draft_job_state.advance_draft_progress") as advance):
            run.accepted = 500
            run.publish()
            self.assertEqual(advance.call_args.kwargs["overall_progress"], 55.0)
            self.assertEqual(advance.call_args.kwargs["generated_characters"], 500)
            run.accepted = 1_000
            run.publish()
            self.assertEqual(advance.call_args.kwargs["overall_progress"], 90.0)

    def test_scheduler_is_fixed_and_expands_for_long_or_low_yield_jobs(self):
        normal = draft_schedule.planned_call_budget(4, structured=True)
        self.assertEqual(normal["predicted"], 4)
        self.assertEqual(normal["batch"], 1)
        self.assertEqual(normal["coverage"], 3)
        self.assertEqual(normal["ending"], 2)
        self.assertEqual(normal["hardCap"], normal["total"])
        low_yield = draft_schedule.required_developments(3_000, capacity=600, yield_ratio=.25)
        long_job = draft_schedule.required_developments(10_800, capacity=600, yield_ratio=1.0)
        self.assertEqual(low_yield, 6)
        self.assertEqual(long_job, 19)
        self.assertGreater(draft_schedule.planned_call_budget(low_yield, structured=True)["total"], 3)
        self.assertEqual(draft_schedule.planned_call_budget(4, structured=False)["coverage"], 3)

    def test_learned_batch_changes_prediction_but_not_the_safety_floor(self):
        unknown = draft_schedule.planned_call_budget(7, structured=True)
        learned = draft_schedule.planned_call_budget(7, structured=True, learned_batch=3)
        self.assertEqual(unknown["hardCap"], learned["hardCap"])
        self.assertEqual((unknown["predicted"], learned["predicted"]), (7, 3))

    def test_recovery_never_consumes_the_ending_escrow(self):
        run = object.__new__(DraftDialogueRun)
        run.coverage_queue = ["D2", "D3", "D4"]
        run.recovery_queue = ["D1"]
        run.ending_source = "D5"
        run.ending_pending = True
        run.batch_size = 1
        run.request = SimpleNamespace(target_minutes=15, speech_rate=1.0, line_gap=.7)
        run.max_block = 1800
        run.accepted, run.target = 2821, 5616
        run.planned_targets = {"D1": 600, "D2": 600, "D3": 600, "D4": 600, "D5": 480}
        run.source_characters = {}
        run.developments = [[f"{source}|展開" for source in run.planned_targets]]
        run.drafted = []
        run.calls, run.call_limit = 5, 9
        selected, sources, _, _ = run.select()
        self.assertEqual(sources, ["D2"])
        self.assertEqual(selected, ["D2|展開"])
        run.coverage_queue.clear()
        run.recovery_queue.clear()
        _, sources, _, _ = run.select()
        self.assertEqual(sources, ["D5"])

    def test_empty_ending_does_not_schedule_blind_regeneration(self):
        run = object.__new__(DraftDialogueRun)
        run.coverage_queue, run.recovery_queue = [], []
        run.ending_source, run.ending_pending = "END", True
        run.attempt_counts = {"END": 1}
        run.completed, run.finalized_incomplete = [], set()
        run.developments, run.pending = [["END|結末"]], [["END|結末"]]
        run._resolve_attempt(["END"], set(), useful=False)
        self.assertFalse(run.ending_pending)

    def test_completed_job_discards_stale_no_usable_output_warning(self):
        run = object.__new__(DraftDialogueRun)
        run.pending = [[], []]
        run.finalized_incomplete = set()
        run.stop_reason = "draft_no_usable_output"
        self.assertEqual(run.completion_reasons(), "")
        self.assertEqual(run.stop_reason, "")

    def test_call_prediction_adapts_to_semantic_plan_and_capacity(self):
        targets = {"D1": 500, "D2": 500, "D3": 500, "D4": 500}
        self.assertEqual(draft_packet_budget.predicted_packet_calls(targets, 2_000, 4), 1)
        self.assertEqual(draft_packet_budget.predicted_packet_calls(targets, 900, 4), 4)
        self.assertEqual(draft_packet_budget.predicted_packet_calls(targets, 2_000, 2), 2)

    def test_three_minutes_uses_two_packets_including_every_source_and_ending(self):
        request = SimpleNamespace(target_minutes=3, speech_rate=1.2, line_gap=0.7)
        target = draft_packet_budget.duration_character_target(request)
        self.assertLess(target, 1296)
        limit = draft_packet_budget.packet_call_limit(target, 1426)
        self.assertEqual(limit, 2)
        pending = [["D1|挨拶", "D2|自己紹介"], ["D3|応答", "AUTHOR_ENDING|結び"]]
        first = draft_packet_budget.next_packet(pending=pending, calls=0, accepted=0,
            generation_target=target, max_block=1426, max_calls=limit, planned_targets={})
        second = draft_packet_budget.next_packet(pending=[[], pending[1]], calls=1, accepted=first[1],
            generation_target=target, max_block=1426, max_calls=limit, planned_targets={})
        self.assertEqual(first[0] + second[0], pending[0] + pending[1])
        self.assertTrue(second[-1])
        self.assertLessEqual(first[1] + second[1], target + 1)

    def test_plain_protocol_retains_sources_and_only_closed_sources_are_complete(self):
        response = ("::SOURCE|D1\nNORMAL|A|こんにちは。||rate=bad|direction=明るく\n"
                    "::SOURCE_END|D1\n::SOURCE|D2\nSIM:S1|B|よろしく。||gap=0.7\nBROKEN")
        rows = parse_scoped_dialogue(response, allowed_speakers={"A", "B"})["lines"]
        self.assertEqual([row["development_id"] for row in rows], ["D1", "D2"])
        self.assertTrue(rows[0]["source_complete"])
        self.assertNotIn("source_complete", rows[1])
        self.assertEqual(rows[0]["integrated_direction"]["direction"], "明るく")
        self.assertEqual(rows[1]["integrated_direction"]["cue"], "SIM:S1")

    def test_retry_budget_does_not_reset_between_calls(self):
        context = SimpleNamespace(retry_budget=llm_retry_budget.DraftRetryBudget())
        error = llm_transport.TransportFailure("overloaded", "response", status=503)
        with patch.object(runtime_state, "DRAFT_LLM_THREAD_CONTEXT", context), \
             patch.object(llm_transport, "cancellable_wait"):
            llm_transport.retry_or_raise(error, 1, None)
            llm_transport.retry_or_raise(error, 1, None)
            with self.assertRaises(llm_transport.TransportFailure):
                llm_transport.retry_or_raise(error, 1, None)
            self.assertEqual(context.retry_budget.retries, 2)

    def test_google_retry_delay_and_daily_quota(self):
        body = '{"error":{"details":[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"90.5s"}]}}'
        self.assertEqual(llm_retry_budget.retry_details(body), (90.5, False))
        self.assertEqual(llm_transport.retry_after_seconds("90"), 90)
        self.assertEqual(llm_transport.retry_delay(1, 90), 90)
        body = '{"error":{"details":[{"@type":"type.googleapis.com/google.rpc.QuotaFailure","violations":[{"quotaId":"RequestsPerDay-FreeTier"}]}]}}'
        self.assertEqual(llm_retry_budget.retry_details(body), (None, True))
        self.assertFalse(llm_transport.is_retryable(llm_transport.TransportFailure("quota_exhausted", "response", status=429)))

    def test_failed_estimates_are_not_billed_usage(self):
        operation = "budget-regression"
        begin_llm_operation(operation, "test")
        record_llm_call(operation_id=operation, usage={"promptTokens": 19076, "completionTokens": 3839,
                        "totalTokens": 25063}, input_estimate=0, output_text="usable")
        record_llm_call(operation_id=operation, usage=None, input_estimate=78122, output_text="", failed=True)
        usage = next(row for row in session_usage()["history"] if row["id"] == operation)["usage"]
        self.assertEqual(usage["inputTokens"], 19076)
        self.assertEqual(usage["totalTokens"], 25063)
        self.assertEqual(usage["unconfirmedInputTokens"], 78122)
        self.assertEqual(usage["unknownUsageCalls"], 1)
        self.assertEqual(usage["unattributedTokens"], 2148)

"""Capacity fitting keeps fixed author material and reserves unfinished endings."""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import server.app  # noqa: F401
from server.registry import deps
from server.modules.draft_call_fit import fit_dialogue_request
from server.modules.draft_dialogue_job import DraftDialogueRun
from server.modules.ollama_context import DraftContextError


class DraftCallFitTests(unittest.TestCase):
    def payload(self):
        return {"sections": [{"theme_or_situation": "作者の指示。"},
            {"participating_casts": [{"profile": "長い設定" * 200}]},
            {"current_packet": [{"beats": ["D1|途中", "D2|結末"], "final_conclusion": True}]},
            {"accepted_dialogue_and_current_request": {"recommended_new_line_count": 50,
                "source_target_characters": {"D1": 1000, "D2": 1000},
                "accepted_dialogue_so_far": "受理済み本文" * 300}}]}

    def test_reduce_only_new_work_and_never_mark_dropped_ending_as_current(self):
        user = self.payload()
        original = copy.deepcopy(user)
        with patch("server.modules.draft_capability.active_draft_capability_profile",
                   return_value={"jobContext": 8192}), \
             patch("server.modules.draft_capability.estimate_llm_input_tokens", return_value=6000):
            sources, requested, output = fit_dialogue_request(None, "system", user, 2000, 4096)
        self.assertEqual(sources, ["D1"])
        self.assertLess(requested, 2000)
        self.assertLessEqual(6000 + output + deps.DRAFT_CONTEXT_SAFETY_MARGIN, 8192)
        self.assertEqual(user["sections"][:2], original["sections"][:2])
        self.assertEqual(user["sections"][3]["accepted_dialogue_and_current_request"]["accepted_dialogue_so_far"],
                         original["sections"][3]["accepted_dialogue_and_current_request"]["accepted_dialogue_so_far"])
        self.assertFalse(user["sections"][2]["current_packet"][0]["final_conclusion"])

    def test_fixed_information_failure_does_not_shorten_profile_or_history(self):
        user = self.payload()
        original = copy.deepcopy(user)
        with patch("server.modules.draft_capability.active_draft_capability_profile",
                   return_value={"jobContext": 4096}), \
             patch("server.modules.draft_capability.estimate_llm_input_tokens", return_value=4000):
            with self.assertRaises(DraftContextError):
                fit_dialogue_request(None, "system", user, 2000, 4096)
        self.assertEqual(user, original)

    def test_elapsed_duration_reduces_later_work_and_retains_final_scene(self):
        run = object.__new__(DraftDialogueRun)
        run.request = SimpleNamespace(target_minutes=3, speech_rate=1.2, line_gap=.7)
        run.planned_targets = {"D1": 400, "D2": 400, "D3": 300}
        run.source_characters, run.completed = {"D1": 700}, ["D1"]
        run.pending, run.calls, run.call_limit = [[], ["D2|展開", "D3|結末"]], 1, 5
        run.accepted, run.target, run.max_block, run.batch_size = 700, 1100, 2000, 2
        run.drafted = [{"dialogue": {"lines": [{"text": "あ" * 700,
            "integrated_direction": {"rate": ".85", "gap": "1"}}]}}]
        selected, sources, requested, targets = run.select()
        self.assertEqual(sources, ["D2"])
        self.assertEqual(len(selected), 1)
        self.assertLessEqual(requested, 400)
        self.assertGreater(targets["D2"], 0)

    def test_observed_yield_adjusts_new_work_but_never_inflates_the_ending(self):
        from server.modules.draft_packet_budget import adjust_for_observed_yield
        targets = {"D1": 500, "D2": 500, "END": 320}
        result = adjust_for_observed_yield(targets, [{"requested": 1000, "accepted": 500}], 1800, "END", 320)
        self.assertEqual(result, {"D1": 740, "D2": 740, "END": 320})
        self.assertEqual(adjust_for_observed_yield(targets, [], 1800, "END", 320), targets)
        end_only = adjust_for_observed_yield({"END": 800}, [{"requested": 1000, "accepted": 200}], 1800, "END", 320)
        self.assertEqual(end_only, {"END": 320})

if __name__ == "__main__":
    unittest.main()

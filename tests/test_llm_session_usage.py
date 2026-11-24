from __future__ import annotations

import unittest
from uuid import uuid4

from server.modules.llm_session_usage import (
    begin_llm_operation,
    finish_llm_operation,
    record_llm_call,
    reset_session_usage,
    session_usage,
)


class LlmSessionUsageTests(unittest.TestCase):
    def test_combines_reported_and_estimated_fields_per_operation(self) -> None:
        operation_id = f"test_{uuid4()}"
        begin_llm_operation(operation_id, "AI台本生成", "openai", "model-a")
        record_llm_call(operation_id=operation_id,
                        usage={"promptTokens": 10, "completionTokens": 4, "totalTokens": 14, "cachedTokens": 3},
                        input_estimate=99, output_text="ignored")
        record_llm_call(operation_id=operation_id, usage={"totalTokens": 8},
                        input_estimate=5, output_text="abcd")
        finish_llm_operation(operation_id, "completed")

        operation = next(item for item in session_usage()["history"] if item["id"] == operation_id)
        self.assertEqual(operation["usage"]["totalTokens"], 22)
        self.assertEqual(operation["usage"]["cachedInputTokens"], 3)
        self.assertEqual(operation["callCount"], 2)
        self.assertEqual(operation["classification"], "partial")
        self.assertEqual(operation["status"], "completed")

    def test_missing_usage_keeps_estimated_input_and_partial_output(self) -> None:
        operation_id = f"test_{uuid4()}"
        begin_llm_operation(operation_id, "発音提案")
        call = record_llm_call(operation_id=operation_id, usage=None, input_estimate=7, output_text="日本語")
        self.assertEqual(call["inputTokens"], 7)
        self.assertGreater(call["outputTokens"], 0)
        self.assertTrue(call["totalEstimated"])

    def test_reset_clears_totals_and_starts_a_new_session(self) -> None:
        operation_id = f"test_{uuid4()}"
        begin_llm_operation(operation_id, "リセット対象")
        record_llm_call(operation_id=operation_id, usage={"totalTokens": 8}, input_estimate=5, output_text="abc")
        before = session_usage()["sessionStartedAt"]

        reset = reset_session_usage()

        self.assertGreater(reset["sessionStartedAt"], before)
        self.assertEqual(reset["total"]["totalTokens"], 0)
        self.assertEqual(reset["history"], [])


if __name__ == "__main__":
    unittest.main()

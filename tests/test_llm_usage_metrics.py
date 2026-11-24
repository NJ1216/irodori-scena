from __future__ import annotations

import unittest

from server.modules.llm_client import extract_usage_metrics


class LlmUsageMetricsTests(unittest.TestCase):
    def test_cached_tokens_are_read_from_openai_prompt_details(self) -> None:
        self.assertEqual(
            extract_usage_metrics({"usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
                "prompt_tokens_details": {"cached_tokens": 80},
            }}),
            {"promptTokens": 120, "completionTokens": 30, "cachedTokens": 80, "totalTokens": 150},
        )

    def test_missing_and_unknown_usage_are_ignored(self) -> None:
        self.assertEqual(extract_usage_metrics({}), {})
        self.assertEqual(extract_usage_metrics({"usage": {"total_tokens": "unknown"}}), {})


if __name__ == "__main__":
    unittest.main()

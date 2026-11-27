from __future__ import annotations

import scena_test_isolation  # noqa: F401
import logging
import unittest

from server.access_logging import RoutinePollingFilter, install_access_log_filter


def access_record(method: str, path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', (("127.0.0.1", 1234), method, path, "1.1", status), None)


class RoutinePollingFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.filter = RoutinePollingFilter()

    def test_suppresses_only_successful_memory_polling(self) -> None:
        self.assertFalse(self.filter.filter(access_record("GET", "/api/system/memory", 200)))
        self.assertFalse(self.filter.filter(access_record("GET", "/api/system/memory?sample=1", 200)))
        self.assertFalse(self.filter.filter(access_record("GET", "/api/llm/session-usage", 200)))
        self.assertTrue(self.filter.filter(access_record("GET", "/api/system/memory", 500)))
        self.assertTrue(self.filter.filter(access_record("GET", "/api/llm/session-usage", 503)))
        self.assertTrue(self.filter.filter(access_record("POST", "/api/system/memory", 200)))
        self.assertTrue(self.filter.filter(access_record("GET", "/api/health", 200)))

    def test_preserves_unrecognized_log_records(self) -> None:
        record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, "plain message", (), None)
        self.assertTrue(self.filter.filter(record))

    def test_installation_is_idempotent(self) -> None:
        logger = logging.getLogger("uvicorn.access")
        original = list(logger.filters)
        try:
            logger.filters.clear()
            install_access_log_filter()
            install_access_log_filter()
            self.assertEqual(sum(isinstance(item, RoutinePollingFilter) for item in logger.filters), 1)
        finally:
            logger.filters[:] = original


if __name__ == "__main__":
    unittest.main()

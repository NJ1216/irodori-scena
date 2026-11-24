"""Keep Uvicorn access logs useful by hiding only routine successful polling."""

from __future__ import annotations

import logging

ROUTINE_POLLING_PATHS = frozenset({"/api/system/memory", "/api/llm/session-usage"})


class RoutinePollingFilter(logging.Filter):
    """Suppress the successful memory-meter poll without hiding failures."""

    def filter(self, record: logging.LogRecord) -> bool:
        arguments = record.args
        if not isinstance(arguments, tuple) or len(arguments) < 5:
            return True
        _client, method, path, _http_version, status = arguments[:5]
        request_path = str(path).partition("?")[0]
        return not (method == "GET" and request_path in ROUTINE_POLLING_PATHS and status == 200)


def install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RoutinePollingFilter) for item in logger.filters):
        logger.addFilter(RoutinePollingFilter())

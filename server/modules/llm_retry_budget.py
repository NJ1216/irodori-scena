"""One retry budget per draft, with endpoint cooldowns shared across its calls."""
from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field

from server.registry import deps


@dataclass
class DraftRetryBudget:
    retries: int = 0
    stopped: BaseException | None = None
    nonstream: set[str] = field(default_factory=set)


_LOCK = threading.RLock()
_COOLDOWNS: dict[str, float] = {}


def current_budget() -> DraftRetryBudget | None:
    return getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "retry_budget", None)


def before_attempt(request, should_cancel) -> None:
    budget = current_budget()
    if budget and budget.stopped:
        raise budget.stopped
    key = request.base_url.rstrip("/")
    with _LOCK:
        delay = max(0.0, _COOLDOWNS.get(key, 0) - time.monotonic())
    if delay:
        if delay > 120:
            raise deps.TransportFailure("retry_later", "cooldown", retry_after=delay)
        deps.cancellable_wait(delay, should_cancel)
    deps._raise_if_draft_cancelled(should_cancel)
    job_id = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None)
    if job_id:
        with deps.DRAFT_JOBS_LOCK:
            job = deps.DRAFT_JOBS.get(job_id)
            if job is not None:
                job["transportCallCount"] = int(job.get("transportCallCount", 0)) + 1


def reserve_retry(error: BaseException) -> int | None:
    budget = current_budget()
    if budget is None:
        return None
    if budget.stopped or budget.retries >= 2:
        budget.stopped = error
        raise error
    budget.retries += 1
    return budget.retries


def remember_cooldown(request, delay: float) -> None:
    with _LOCK:
        now = time.monotonic()
        for key in list(_COOLDOWNS):
            if _COOLDOWNS[key] <= now:
                del _COOLDOWNS[key]
        key = request.base_url.rstrip("/")
        _COOLDOWNS[key] = max(_COOLDOWNS.get(key, 0), now + delay)


def retry_details(body: str) -> tuple[float | None, bool]:
    """Read Google's typed retry/quota details, never return raw error content."""
    try:
        value = json.loads(body)
        if isinstance(value, list):
            value = next((item for item in value if isinstance(item, dict)), {})
        details = value.get("error", {}).get("details", [])
    except (ValueError, AttributeError, TypeError):
        return None, False
    delay, daily = None, False
    for item in details if isinstance(details, list) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("@type", "")).endswith("google.rpc.RetryInfo"):
            try:
                parsed = float(str(item.get("retryDelay", "")).removesuffix("s"))
                if math.isfinite(parsed) and parsed >= 0:
                    delay = max(delay or 0, parsed)
            except ValueError:
                pass
        if str(item.get("@type", "")).endswith("google.rpc.QuotaFailure"):
            violations = item.get("violations")
            daily = daily or any(isinstance(row, dict) and "perday" in str(row.get("quotaId", "")).lower()
                                 for row in (violations if isinstance(violations, list) else []))
    return delay, daily


def http_failure(request, status: int, body: str, retry_header: str | None):
    failure = deps.classify_http_failure(status, body)
    body_delay, daily = retry_details(body)
    header_delay = deps.retry_after_seconds(retry_header)
    values = [item for item in (body_delay, header_delay) if item is not None]
    delay = max(values) if values else (60.0 if status == 429 else None)
    category = "quota_exhausted" if daily else failure.category
    if delay is not None:
        remember_cooldown(request, delay)
    # Long waits remain cooldowns, not shortened waits followed by an early send.
    if delay is not None and delay > 120:
        category = "retry_later"
    return deps.TransportFailure(category, failure.stage, status=status, retry_after=delay)

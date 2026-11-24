"""Immutable budgets and adaptive batches for finite long-form drafting."""
from __future__ import annotations

import math


INTRO_TARGET = 320
ENDING_TARGET = 480
MIN_DEVELOPMENT_TARGET = 400
MAX_DEVELOPMENT_TARGET = 900


def development_capacity(max_chunk_characters: int) -> int:
    return max(MIN_DEVELOPMENT_TARGET, min(MAX_DEVELOPMENT_TARGET, int(max_chunk_characters)))


def required_developments(target_characters: int, *, capacity: int, yield_ratio: float = 1.0) -> int:
    """Return semantic beats; observed yield selects capacity, never inflates a request."""
    del yield_ratio
    target = max(1, int(target_characters))
    body_capacity = development_capacity(capacity)
    if target <= INTRO_TARGET + ENDING_TARGET:
        return 2
    return 2 + math.ceil((target - INTRO_TARGET - ENDING_TARGET) / body_capacity)


def planned_call_budget(developments: int, *, structured: bool, learned_batch: int | None = None,
                        elastic_developments: int | None = None) -> dict[str, int]:
    """Freeze prediction separately from a coverage/recovery/ending safety cap."""
    count = max(1, int(developments))
    coverage = max(0, count - 1)
    batch = max(1, min(3, int(learned_batch or 1))) if structured else 1
    predicted_coverage = math.ceil(coverage / batch)
    predicted = predicted_coverage + 1
    elastic = max(0, int(elastic_developments if elastic_developments is not None else math.ceil(coverage / 3)))
    recovery = coverage + elastic
    ending = 2
    hard_cap = coverage + recovery + ending
    return {
        "predicted": predicted, "hardCap": hard_cap, "batch": batch,
        "coverage": coverage, "recovery": recovery, "ending": ending,
        "primary": predicted_coverage + 1, "reserve": hard_cap - predicted,
        "total": hard_cap,
    }

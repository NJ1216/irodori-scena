from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass(order=True)
class QueuedWork:
    priority: int
    order: int
    project_key: str = field(compare=False)
    signature: str = field(compare=False)
    request_id: str = field(compare=False)


@dataclass
class PreparationPlan:
    project_key: str
    boundaries: dict[str, dict[str, Any]]


@dataclass
class PlaybackWindow:
    project_key: str
    line_ids: list[str]
    deadlines: dict[str, float]
    window_announced: bool = False


@dataclass
class PreparationWork:
    request_id: str
    project_key: str
    signature: str
    leading_line_id: str
    boundary: dict[str, Any]
    priority: int
    line_ids: set[str] = field(default_factory=set)
    cancel: threading.Event = field(default_factory=threading.Event)
    complete: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: BaseException | None = None
    invalidated: bool = False

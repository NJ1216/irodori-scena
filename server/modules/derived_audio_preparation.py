from __future__ import annotations

import heapq
import threading
import time
from typing import Any
from uuid import uuid4

from server.modules.derived_audio_state import PlaybackWindow as _Playback
from server.modules.derived_audio_state import PreparationPlan as _Plan
from server.modules.derived_audio_state import PreparationWork as _Work
from server.modules.derived_audio_state import QueuedWork as _Queued
from server.registry import deps


_CONDITION = threading.Condition()
_QUEUE: list[_Queued] = []
_ORDER = 0
_WORKER: threading.Thread | None = None
_WORK: dict[tuple[str, str], _Work] = {}
_STATE: dict[tuple[str, str], dict[str, Any]] = {}
_PLAYBACKS: dict[str, _Playback] = {}
_ACTIVE_PLAYBACKS: dict[str, str] = {}
_PLANS: dict[str, _Plan] = {}
_CURRENT_PROJECT_KEY: str | None = None
_ACTIVE: _Work | None = None


def _project_key(_project: dict[str, Any]) -> str:
    revision = _project.get("revision", 0)
    return f"{deps.PROJECT_FILE.resolve()}@{revision}"


def _publish(work: _Work, status: str, **details: Any) -> None:
    with _CONDITION:
        for line_id in work.line_ids:
            key = (work.project_key, line_id)
            previous = _STATE.get(key, {})
            _STATE[key] = {**previous, "leadingLineId": line_id, "status": status, **details}


def _urgent_ids(project_key: str) -> set[str]:
    return {
        line_id
        for playback in _PLAYBACKS.values()
        if playback.project_key == project_key
        for line_id in playback.line_ids
    }


def _urgent_missing(project_key: str) -> bool:
    return any(_STATE.get((project_key, line_id), {}).get("status") != "ready" for line_id in _urgent_ids(project_key))


def _line_ready(project_key: str, line_id: str) -> bool:
    return _STATE.get((project_key, line_id), {}).get("status") == "ready"


def _background_allowed(project_key: str) -> bool:
    playback_id = _ACTIVE_PLAYBACKS.get(project_key)
    if playback_id is None:
        return True
    playback = _PLAYBACKS.get(playback_id)
    return bool(playback and playback.window_announced and not _urgent_missing(project_key))


def _valid_pending_work() -> bool:
    if _ACTIVE is not None:
        return True
    return any(
        (work := _WORK.get((queued.project_key, queued.signature))) is not None
        and work.request_id == queued.request_id
        and work.priority == queued.priority
        and not work.complete.is_set()
        for queued in _QUEUE
    )


def _enqueue(project_key: str, line_id: str, priority: int) -> _Work:
    global _ORDER
    plan = _PLANS.get(project_key)
    if plan is None or line_id not in plan.boundaries:
        raise KeyError(f"Overlap boundary is not in the current project plan: {line_id}")
    boundary = plan.boundaries[line_id]
    signature = str(boundary["signature"])
    key = (project_key, signature)
    existing = _WORK.get(key)
    if existing:
        existing.line_ids.add(line_id)
        if existing.complete.is_set():
            if existing.result is not None and existing.error is None:
                previous = _STATE.get((project_key, line_id), {})
                _STATE[(project_key, line_id)] = {
                    **previous,
                    "leadingLineId": line_id,
                    "status": "ready",
                    "signature": signature,
                    "audioUrl": existing.result["audioUrl"],
                }
                return existing
        elif priority < existing.priority:
            existing.priority = priority
            _ORDER += 1
            heapq.heappush(_QUEUE, _Queued(priority, _ORDER, project_key, signature, existing.request_id))
            return existing
        else:
            return existing
    work = _Work(uuid4().hex, project_key, signature, line_id, boundary, priority, {line_id})
    _WORK[key] = work
    _ORDER += 1
    heapq.heappush(_QUEUE, _Queued(priority, _ORDER, project_key, signature, work.request_id))
    previous = _STATE.get((project_key, line_id), {})
    _STATE[(project_key, line_id)] = {
        **previous,
        "leadingLineId": line_id,
        "status": "queued",
        "priority": priority,
        "queuedAt": time.time(),
    }
    return work


def _reset_unfinished_work(work: _Work) -> None:
    if _WORK.get((work.project_key, work.signature)) is work:
        _WORK.pop((work.project_key, work.signature), None)
    for line_id in work.line_ids:
        previous = _STATE.get((work.project_key, line_id), {})
        _STATE[(work.project_key, line_id)] = {
            **previous,
            "leadingLineId": line_id,
            "status": "idle",
        }


def _interrupt_background(project_key: str, required: set[str] | None = None) -> None:
    required = required or set()
    if _ACTIVE and _ACTIVE.project_key == project_key and _ACTIVE.priority >= 10 and not (_ACTIVE.line_ids & required):
        _ACTIVE.cancel.set()
    removed: dict[str, _Work] = {}
    retained: list[_Queued] = []
    for queued in _QUEUE:
        work = _WORK.get((queued.project_key, queued.signature))
        if queued.project_key == project_key and work and work.priority >= 10 and not (work.line_ids & required):
            removed[work.request_id] = work
        else:
            retained.append(queued)
    if len(retained) != len(_QUEUE):
        _QUEUE[:] = retained
        heapq.heapify(_QUEUE)
    for work in removed.values():
        if work is not _ACTIVE:
            _reset_unfinished_work(work)


def _invalidate_work(project_key: str, signatures: set[str] | None = None) -> None:
    def matches(work: _Work) -> bool:
        return work.project_key == project_key and (signatures is None or work.signature in signatures)

    removed = [work for work in _WORK.values() if matches(work)]
    for work in removed:
        _WORK.pop((work.project_key, work.signature), None)
    _QUEUE[:] = [
        queued
        for queued in _QUEUE
        if not (queued.project_key == project_key and (signatures is None or queued.signature in signatures))
    ]
    heapq.heapify(_QUEUE)
    for work in removed:
        work.invalidated = True
        if work is _ACTIVE:
            work.cancel.set()
        else:
            work.error = RuntimeError("Overlap preparation was invalidated by a project change.")
            work.complete.set()
            _publish(work, "interrupted")


def _schedule_background(project_key: str) -> bool:
    if project_key != _CURRENT_PROJECT_KEY or not _background_allowed(project_key) or _valid_pending_work():
        return False
    plan = _PLANS.get(project_key)
    if plan is None:
        return False
    for line_id, boundary in plan.boundaries.items():
        work = _WORK.get((project_key, str(boundary["signature"])))
        if work is None:
            _enqueue(project_key, line_id, 10)
            return True
        if not work.complete.is_set():
            return False
    return False


def _worker_loop() -> None:
    global _ACTIVE
    while True:
        with _CONDITION:
            while not _QUEUE:
                _CONDITION.wait()
            queued = heapq.heappop(_QUEUE)
            work = _WORK.get((queued.project_key, queued.signature))
            if (
                not work
                or work.request_id != queued.request_id
                or work.complete.is_set()
                or queued.priority != work.priority
            ):
                continue
            if work.priority >= 10 and not _background_allowed(work.project_key):
                _reset_unfinished_work(work)
                continue
            _ACTIVE = work
        try:
            started_at = time.time()
            queued_at = min(
                (
                    float(_STATE.get((work.project_key, line_id), {}).get("queuedAt", started_at))
                    for line_id in work.line_ids
                ),
                default=started_at,
            )
            _publish(work, "rendering", startedAt=started_at, queueWaitMs=max(0.0, (started_at - queued_at) * 1000))
            result = deps.render_prepared_overlap(work.boundary, should_cancel=work.cancel.is_set)
            if work.invalidated or work.cancel.is_set():
                raise InterruptedError
            work.result = result
            _publish(work, "ready", signature=work.result["signature"], audioUrl=work.result["audioUrl"])
        except InterruptedError:
            _publish(work, "interrupted")
            with _CONDITION:
                work.cancel.clear()
                if work.invalidated:
                    work.error = RuntimeError("Overlap preparation belongs to an inactive project generation.")
                elif work.priority >= 10:
                    _reset_unfinished_work(work)
                _CONDITION.notify_all()
        except BaseException as error:
            work.error = error
            _publish(work, "failed", error=str(error))
        finally:
            with _CONDITION:
                if _ACTIVE is work:
                    _ACTIVE = None
                if work.result is not None or work.error is not None:
                    work.complete.set()
                _schedule_background(_CURRENT_PROJECT_KEY or work.project_key)
                _CONDITION.notify_all()


def _ensure_worker() -> None:
    global _WORKER
    with _CONDITION:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_worker_loop, name="scena-derived-audio", daemon=True)
            _WORKER.start()


def start_overlap_preparation(project: dict[str, Any] | None = None) -> dict[str, Any]:
    global _CURRENT_PROJECT_KEY
    project = project or deps.read_project()
    project_key = _project_key(project)
    plan = _Plan(project_key, deps.prepare_overlap_boundaries(project))
    boundaries = list(plan.boundaries)
    with _CONDITION:
        if _CURRENT_PROJECT_KEY is not None and _CURRENT_PROJECT_KEY != project_key:
            _invalidate_work(_CURRENT_PROJECT_KEY)
            _PLAYBACKS.clear()
            _ACTIVE_PLAYBACKS.clear()
        _PLANS[project_key] = plan
        _CURRENT_PROJECT_KEY = project_key
        valid = {(project_key, line_id) for line_id in boundaries}
        for key in [key for key in _STATE if key[0] == project_key and key not in valid]:
            _STATE.pop(key, None)
        for line_id in boundaries:
            _STATE.setdefault(
                (project_key, line_id),
                {"leadingLineId": line_id, "status": "idle"},
            )
        scheduled = _schedule_background(project_key)
        _CONDITION.notify_all()
    if scheduled:
        _ensure_worker()
    return {"projectKey": project_key, "boundaries": boundaries}


def refresh_overlap_preparation(project: dict[str, Any]) -> dict[str, Any]:
    """Replace the active plan while retaining work whose signature is unchanged."""
    from server.modules.timeline_queue import QUEUE
    from server.modules.timeline import project_timeline
    if QUEUE.background_plan_id is not None:
        QUEUE.background_plan(project_timeline(project))
    with _CONDITION:
        project_key = _CURRENT_PROJECT_KEY
        previous = _PLANS.get(project_key or "")
    if project_key is None or previous is None:
        return {"updated": False, "changedBoundaryIds": []}
    boundaries = deps.prepare_overlap_boundaries(project)
    old_signatures = {line_id: str(value["signature"]) for line_id, value in previous.boundaries.items()}
    new_signatures = {line_id: str(value["signature"]) for line_id, value in boundaries.items()}
    changed = {
        line_id
        for line_id in old_signatures.keys() | new_signatures.keys()
        if old_signatures.get(line_id) != new_signatures.get(line_id)
    }
    with _CONDITION:
        if _CURRENT_PROJECT_KEY != project_key or _PLANS.get(project_key) is not previous:
            return {"updated": False, "changedBoundaryIds": []}
        retained_signatures = set(new_signatures.values())
        _invalidate_work(project_key, set(old_signatures.values()) - retained_signatures)
        _PLANS[project_key] = _Plan(project_key, boundaries)
        previous_state = {line_id: value for (key, line_id), value in _STATE.items() if key == project_key}
        for key in [key for key in _STATE if key[0] == project_key]:
            _STATE.pop(key, None)
        by_signature: dict[str, set[str]] = {}
        for line_id, signature in new_signatures.items():
            by_signature.setdefault(signature, set()).add(line_id)
            work = _WORK.get((project_key, signature))
            state = previous_state.get(line_id, {}) if old_signatures.get(line_id) == signature else {}
            if work and work.complete.is_set() and work.result is not None and work.error is None:
                state = {**state, "status": "ready", "signature": signature, "audioUrl": work.result["audioUrl"]}
            _STATE[(project_key, line_id)] = {"leadingLineId": line_id, "status": "idle", **state}
        for signature, line_ids in by_signature.items():
            work = _WORK.get((project_key, signature))
            if work:
                work.line_ids = line_ids
                work.leading_line_id = next(iter(line_ids))
                work.boundary = boundaries[work.leading_line_id]
        for playback in _PLAYBACKS.values():
            if playback.project_key == project_key:
                playback.line_ids = [line_id for line_id in playback.line_ids if line_id in boundaries]
                playback.deadlines = {
                    line_id: value for line_id, value in playback.deadlines.items() if line_id in boundaries
                }
        active_id = _ACTIVE_PLAYBACKS.get(project_key)
        active_playback = _PLAYBACKS.get(active_id or "")
        urgent = list(active_playback.line_ids) if active_playback else []
        if any(not _line_ready(project_key, line_id) for line_id in urgent):
            _interrupt_background(project_key, set(urgent))
        for rank, line_id in enumerate(urgent[:2]):
            _enqueue(project_key, line_id, rank)
        scheduled = _schedule_background(project_key)
        _CONDITION.notify_all()
    if scheduled or urgent:
        _ensure_worker()
    return {"updated": True, "changedBoundaryIds": sorted(changed)}


def reset_overlap_preparation() -> None:
    from server.modules.timeline_queue import QUEUE
    QUEUE.reset()
    global _CURRENT_PROJECT_KEY
    with _CONDITION:
        if _CURRENT_PROJECT_KEY is not None:
            _invalidate_work(_CURRENT_PROJECT_KEY)
        _PLAYBACKS.clear()
        _ACTIVE_PLAYBACKS.clear()
        _PLANS.clear()
        _CURRENT_PROJECT_KEY = None
        _CONDITION.notify_all()


def _current_plan() -> _Plan:
    with _CONDITION:
        plan = _PLANS.get(_CURRENT_PROJECT_KEY or "")
    if plan is not None:
        return plan
    project = deps.read_project()
    start_overlap_preparation(project)
    with _CONDITION:
        return _PLANS[_project_key(project)]


def update_playback(
    playback_id: str,
    line_ids: list[str],
    deadlines_in_ms: dict[str, float] | None = None,
    *,
    start: bool = False,
) -> dict[str, Any]:
    plan = _current_plan()
    project_key = plan.project_key
    requested = list(dict.fromkeys(line_ids))[:2]
    valid = set(plan.boundaries)
    requested = [line_id for line_id in requested if line_id in valid]
    deadlines_in_ms = deadlines_in_ms or {}
    with _CONDITION:
        active_id = _ACTIVE_PLAYBACKS.get(project_key)
        if not start and active_id is not None and active_id != playback_id:
            return {
                "projectKey": project_key,
                "playbackId": playback_id,
                "leadingLineIds": [],
                "stale": True,
            }
        if start:
            for old_id, playback in list(_PLAYBACKS.items()):
                if playback.project_key == project_key and old_id != playback_id:
                    _PLAYBACKS.pop(old_id, None)
        _ACTIVE_PLAYBACKS[project_key] = playback_id
        received_at = time.time()
        deadlines = {
            line_id: received_at + max(0.0, float(deadlines_in_ms.get(line_id, 0))) / 1000 for line_id in requested
        }
        _PLAYBACKS[playback_id] = _Playback(project_key, requested, deadlines, not start)
        if start or any(not _line_ready(project_key, line_id) for line_id in requested):
            _interrupt_background(project_key, set(requested))
        for rank, line_id in enumerate(requested):
            previous = _STATE.get((project_key, line_id), {})
            _STATE[(project_key, line_id)] = {
                **previous,
                "deadlineAt": deadlines[line_id],
                "deadlineInMs": max(0.0, float(deadlines_in_ms.get(line_id, 0))),
            }
            _enqueue(project_key, line_id, rank)
        _schedule_background(project_key)
        _CONDITION.notify_all()
    _ensure_worker()
    return {
        "projectKey": project_key,
        "playbackId": playback_id,
        "leadingLineIds": requested,
    }


def prioritize_overlap_preparation(line_ids: list[str]) -> dict[str, Any]:
    plan = _current_plan()
    project_key = plan.project_key
    valid = set(plan.boundaries)
    with _CONDITION:
        requested = [line_id for line_id in list(dict.fromkeys(line_ids))[:2] if line_id in valid]
        if any(not _line_ready(project_key, line_id) for line_id in requested):
            _interrupt_background(project_key, set(requested))
        for rank, line_id in enumerate(requested):
            _enqueue(project_key, line_id, rank)
        _CONDITION.notify_all()
    _ensure_worker()
    return overlap_preparation_status()


def stop_playback(playback_id: str) -> dict[str, bool]:
    with _CONDITION:
        playback = _PLAYBACKS.pop(playback_id, None)
        if playback and _ACTIVE_PLAYBACKS.get(playback.project_key) == playback_id:
            _ACTIVE_PLAYBACKS.pop(playback.project_key, None)
            _schedule_background(playback.project_key)
        _CONDITION.notify_all()
    _ensure_worker()
    return {"stopped": True}


def request_overlap(leading_line_id: str) -> dict[str, Any]:
    plan = _current_plan()
    if leading_line_id not in plan.boundaries:
        from fastapi import HTTPException
        raise HTTPException(422, "指定された境界は隣接2行mixでは処理できません。")
    project_key = plan.project_key
    with _CONDITION:
        if not _line_ready(project_key, leading_line_id):
            _interrupt_background(project_key, {leading_line_id})
        work = _enqueue(project_key, leading_line_id, 0)
        _CONDITION.notify_all()
    _ensure_worker()
    work.complete.wait()
    if work.error:
        raise work.error
    if work.result is None:
        raise RuntimeError("Overlap preparation ended without a result.")
    result = dict(work.result)
    diagnostics = dict(result.get("diagnostics", {}))
    state = _STATE.get((project_key, leading_line_id), {})
    diagnostics["queueWaitMs"] = round(float(state.get("queueWaitMs", 0.0)), 3)
    result["diagnostics"] = diagnostics
    return result


def overlap_preparation_status() -> dict[str, Any]:
    project_key = _current_plan().project_key
    with _CONDITION:
        boundaries = [dict(value) for (key, _line_id), value in _STATE.items() if key == project_key]
    return {"projectKey": project_key, "boundaries": boundaries}


deps.register(
    __name__,
    [
        "overlap_preparation_status",
        "prioritize_overlap_preparation",
        "refresh_overlap_preparation",
        "reset_overlap_preparation",
        "request_overlap",
        "start_overlap_preparation",
        "stop_playback",
        "update_playback",
    ],
)

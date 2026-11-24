from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from pydantic import BaseModel, Field
from server.registry import deps
from server.modules.timeline import project_timeline, resolved_prefix_end, target_end
from server.modules.timeline_intervals import describe_interval, public_interval
from server.modules.timeline_queue import QUEUE
from server.modules import timeline_sessions


class PlaybackSessionRequest(BaseModel):
    client_id: str = Field(min_length=1, max_length=128)
    playback_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(ge=0)


class TimelineRequest(PlaybackSessionRequest):
    project_id: str
    target_line_ids: list[str] | None = None


class IntervalRequest(TimelineRequest):
    plan_id: str
    start_frame: int = Field(ge=0)
    count: int = Field(default=3, ge=1, le=3)


def _plan(request: TimelineRequest) -> dict[str, Any]:
    project = deps.read_project()
    if project.get("id") != request.project_id:
        raise HTTPException(409, "Playback project changed.")
    timeline_sessions.accept(request.client_id, request.sequence, request.playback_id, str(deps.PROJECT_FILE.resolve()))
    return project_timeline(project)


def _public_plan(plan: dict[str, Any], targets: list[str] | None) -> dict[str, Any]:
    return {
        **plan,
        "targetLineIds": targets,
        "units": [
            {
                **unit,
                "members": [
                    {key: value for key, value in member.items() if key != "path"} for member in unit["members"]
                ],
            }
            for unit in plan["units"]
        ],
    }


@deps.app.post("/api/project/timeline/plan")
def get_timeline_plan(request: TimelineRequest) -> dict[str, Any]:
    return _public_plan(_plan(request), request.target_line_ids)


@deps.app.post("/api/project/timeline/prepare")
def prepare_timeline_intervals(request: IntervalRequest) -> dict[str, Any]:
    plan = _plan(request)
    if plan["planId"] != request.plan_id:
        return {"status": "stale", "plan": _public_plan(plan, request.target_line_ids), "intervals": []}
    rate = plan["sampleRate"]
    targets = set(request.target_line_ids) if request.target_line_ids is not None else None
    intervals = []
    final_end = target_end(plan, targets)
    start = request.start_frame
    for _index in range(request.count):
        end = (start // rate + 1) * rate
        if not plan["resolved"]:
            end = resolved_prefix_end(plan, start, end, targets)
        if final_end is not None:
            end = min(end, final_end)
        if end <= start:
            break
        intervals.append(describe_interval(plan, start, end, targets))
        start = end
    timeline_sessions.accept(request.client_id, request.sequence, request.playback_id, str(deps.PROJECT_FILE.resolve()))
    return {
        "status": "ok",
        "plan": _public_plan(plan, request.target_line_ids),
        "intervals": [public_interval(item) for item in QUEUE.submit(intervals)],
    }


@deps.app.post("/api/project/timeline/stop")
def stop_timeline_playback(request: PlaybackSessionRequest) -> dict[str, bool]:
    timeline_sessions.stop(request.client_id, request.sequence, request.playback_id)
    return {"stopped": True}


@deps.app.post("/api/project/timeline/background")
def prepare_background_timeline() -> dict[str, Any]:
    plan = project_timeline(deps.read_project())
    QUEUE.background_plan(plan)
    return {"projectKey": plan["projectId"], "boundaries": []}

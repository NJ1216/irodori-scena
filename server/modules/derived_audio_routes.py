from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from server.registry import deps


class PreparationRequest(BaseModel):
    leading_line_ids: list[str] = Field(default_factory=list, max_length=2)


class PlaybackBoundaryRequest(BaseModel):
    leading_line_id: str = Field(min_length=1)
    deadline_in_ms: float = Field(ge=0, le=86_400_000)


class PlaybackRequest(PreparationRequest):
    playback_id: str = Field(min_length=1, max_length=128)
    boundaries: list[PlaybackBoundaryRequest] = Field(default_factory=list, max_length=2)


def _playback_boundaries(request: PlaybackRequest) -> tuple[list[str], dict[str, float]]:
    if request.boundaries:
        line_ids = [boundary.leading_line_id for boundary in request.boundaries]
        deadlines = {boundary.leading_line_id: boundary.deadline_in_ms for boundary in request.boundaries}
        return line_ids, deadlines
    return request.leading_line_ids, {}


@deps.app.post("/api/project/derived-audio/prepare")
def prepare_project_derived_audio() -> dict[str, Any]:
    return deps.start_overlap_preparation()


@deps.app.post("/api/project/derived-audio/prioritize")
def prioritize_project_derived_audio(request: PreparationRequest) -> dict[str, Any]:
    return deps.prioritize_overlap_preparation(request.leading_line_ids)


@deps.app.post("/api/project/playback/start")
def start_project_playback(request: PlaybackRequest) -> dict[str, Any]:
    line_ids, deadlines = _playback_boundaries(request)
    return deps.update_playback(request.playback_id, line_ids, deadlines, start=True)


@deps.app.post("/api/project/playback/update")
def update_project_playback(request: PlaybackRequest) -> dict[str, Any]:
    line_ids, deadlines = _playback_boundaries(request)
    return deps.update_playback(request.playback_id, line_ids, deadlines)


@deps.app.post("/api/project/playback/{playback_id}/stop")
def stop_project_playback(playback_id: str) -> dict[str, bool]:
    return deps.stop_playback(playback_id)


@deps.app.get("/api/project/derived-audio/status")
def get_project_derived_audio_status() -> dict[str, Any]:
    return deps.overlap_preparation_status()

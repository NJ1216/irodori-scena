"""Resolve the line inputs shared by synthesis and result acceptance."""

from __future__ import annotations

from typing import Any

from server.registry import deps


def line_speech_timing(project: dict[str, Any], line: dict[str, Any], restore_take: dict[str, Any] | None = None) -> tuple[float, float | None]:
    saved_settings = restore_take.get("settings", {}) if restore_take is not None else {}
    speech_rate = deps.normalize_line_speech_rate(
        saved_settings.get("speechRate") if restore_take is not None else line.get("speechRate"),
        deps.normalize_line_speech_rate(project.get("settings", {}).get("speechRate"), 1.2),
    )
    target_duration = deps.normalize_target_duration(restore_take.get("targetDurationSeconds") if restore_take else line.get("targetDurationSeconds"))
    if target_duration is None:
        target_duration = deps.linked_cue_target_duration(project, line, speech_rate)
    return speech_rate, target_duration


def line_spoken_text(project: dict[str, Any], line: dict[str, Any], restore_take: dict[str, Any] | None = None) -> tuple[str, set[str]]:
    if restore_take is not None and isinstance(restore_take.get("renderedText"), str):
        return restore_take["renderedText"].strip(), set()
    active_character_ids = {str(candidate.get("characterId", "")) for scene in project.get("scenes", []) if isinstance(scene, dict) for candidate in scene.get("lines", []) if isinstance(candidate, dict) if str(candidate.get("characterId", ""))}
    text, used_global_ids = deps.resolve_line_pronunciations(
        str(line.get("text", "")),
        line.get("pronunciations"),
        str(line.get("characterId", "")),
        active_character_ids,
        deps.combined_pronunciation_entries(project),
    )
    return text.strip(), used_global_ids

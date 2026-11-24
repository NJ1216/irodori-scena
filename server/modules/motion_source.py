"""Read-only motion preparation primitives; not a public API or adoption receipt.

Callers supply a detached, reviewed project and a bounded audio-availability probe.
No project reads/writes, generation, selection commits or transport occur here.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Callable, Literal


@dataclass(frozen=True)
class MotionSource:
    project_id: str
    scene_id: str
    line_id: str
    character_id: str
    project_revision: int
    body: str
    selected_take_id: str | None
    selected_take: dict[str, Any] | None
    existing_take_ids: tuple[str, ...]
    generation_reason: Literal["unselected", "missing_record", "unavailable_audio"] | None
    gap_seconds: float | None
    gap_source: Literal["line", "project", "unspecified"]

    @property
    def needs_generation(self) -> bool:
        return self.generation_reason is not None


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Motion source identity is missing.")
    return value


def _unique_record(records: list[dict[str, Any]], identity: str, kind: str) -> dict[str, Any]:
    matches = [record for record in records if record.get("id") == identity]
    if len(matches) != 1:
        raise ValueError(f"Motion {kind} identity is missing or ambiguous.")
    return matches[0]


def _gap(project: dict[str, Any], line: dict[str, Any]) -> tuple[float | None, Literal["line", "project", "unspecified"]]:
    value, source = line.get("gapSeconds"), "line"
    if value is None:
        value, source = project.get("settings", {}).get("lineGap"), "project"
    if value is None:
        return None, "unspecified"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Motion source interval must be finite.")
    return float(value), source


def resolve_motion_source(
    project: dict[str, Any], scene_id: str, line_id: str,
    audio_available: Callable[[dict[str, Any]], bool],
) -> MotionSource:
    """Resolve exact identities; never select an older Take or mutate input.

    The probe must validate managed-path ownership and playable WAV integrity.
    Unexpected probe failures propagate rather than silently imply generation.
    Missing/invalid selected audio requests a new Take, not same-ID restoration.
    """
    project = deepcopy(project)
    project_id = _identity(project.get("id"))
    scene = _unique_record(project.get("scenes", []), _identity(scene_id), "scene")
    line = _unique_record(scene.get("lines", []), _identity(line_id), "line")
    # Existing project services find lines by ID across scenes: reject duplicates.
    _unique_record([item for part in project.get("scenes", []) for item in part.get("lines", [])], line_id, "line")
    revision = project.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Motion source revision must be a nonnegative integer.")
    body = line.get("text")
    if not isinstance(body, str):
        raise ValueError("Motion source dialogue body is missing.")
    selected_id = line.get("selectedTakeId")
    selected, reason = None, "unselected"
    if selected_id is not None:
        selected_id = _identity(selected_id)
        matches = [take for take in line.get("takes", []) if take.get("id") == selected_id]
        if len(matches) > 1:
            raise ValueError("Motion selected Take identity is ambiguous.")
        selected = deepcopy(matches[0]) if matches else None
        reason = "missing_record" if selected is None else None
        if selected is not None and not audio_available(deepcopy(selected)):
            reason = "unavailable_audio"
    gap, gap_source = _gap(project, line)
    return MotionSource(
        project_id, scene_id, line_id, _identity(line.get("characterId")), revision,
        body, selected_id, selected, tuple(_identity(take.get("id")) for take in line.get("takes", [])),
        reason, gap, gap_source,
    )


def _digest(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Motion bundle requires lowercase SHA-256 content identities.")
    return value


def motion_content_version(
    source: MotionSource, *, take_id: str, wav_sha256: str, lab_sha256: str,
    lab_wav_sha256: str, analysis_identity: str,
) -> str:
    """Internal v1 comparison key, pending joint canonicalization review.

    Call only after exact WAV validation and LAB validation/derivation. Matching
    hashes check the declared provenance; they do not prove an analyzer ran.
    Project revision and selection snapshot are concurrency guards, not content.
    Missing intervals stay unresolved; negative values preserve source semantics
    without approving overlapping FCP placement. Paths are deliberately excluded.
    """
    if source.gap_seconds is None:
        raise ValueError("Motion source interval is unspecified.")
    if not source.needs_generation and take_id != source.selected_take_id:
        raise ValueError("Motion prepared Take differs from the selected source Take.")
    if source.needs_generation and (take_id in source.existing_take_ids or take_id == source.selected_take_id):
        raise ValueError("Motion preparation requires a new Take identity.")
    if _digest(wav_sha256) != _digest(lab_wav_sha256):
        raise ValueError("Motion LAB was derived from a different WAV.")
    payload = {
        "identity": [source.project_id, source.scene_id, source.line_id, source.character_id],
        "body": source.body, "take": _identity(take_id), "wav": wav_sha256,
        "lab": _digest(lab_sha256), "analysis": _identity(analysis_identity),
        "gap": source.gap_seconds or 0.0,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "scena-motion-internal-v1:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

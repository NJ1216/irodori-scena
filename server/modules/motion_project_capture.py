"""Read-only adapter from existing typed Project data to internal preparation.

The caller supplies an already acquired Project; no repository, registry, runtime,
reference file or secret is loaded. This is not an active-project/API adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Callable

from server.modules.motion_preparation_artifacts import PreparationRequest, PreparationSnapshot
from server.modules.motion_source import resolve_motion_source
from server.modules.project_models import PersistedTake, StudioProjectModel


@dataclass(frozen=True)
class GenerationEnvironment:
    reference_sha256: str
    engine_commit: str
    model_revision: str
    codec_revision: str
    runtime_variant: str
    external_inputs_identity: str = ""

    def validate(self):
        digest = self.reference_sha256
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("Capture generation reference requires an exact SHA-256 identity.")
        if any(not isinstance(value, str) or not value.strip() for value in asdict(self).values()):
            raise ValueError("Capture generation environment identities are incomplete.")


_LINE_INPUTS = {
    "text", "stageDirection", "pronunciations", "speechRate", "targetDurationSeconds",
    "textCfg", "voiceCfg", "captionCfg", "manualSeed", "fixedSeed",
}
_SETTINGS_INPUTS = {"speechRate", "steps", "textCfg", "voiceCfg", "captionCfg", "seed", "quality"}


def capture_motion_project(
    project: StudioProjectModel, request: PreparationRequest,
    audio_available: Callable[[dict[str, Any]], bool], *,
    generation_environment: GenerationEnvironment | None = None,
) -> PreparationSnapshot:
    """Capture only existing domain fields; selected audio needs no installed model.

    Required generation uses caller-reviewed device-local runtime/reference
    identities rather than legacy project ttsSelection. The inputs token is a
    conservative guard, not the effective renderer's signature or media version.
    The caller must acquire a coherent Project and recheck runtime/reference changes.
    """
    project = project.model_copy(deep=True)
    if project.id != request.project_id:
        raise ValueError("Capture project differs from the requested logical source.")
    projection = {"id": project.id, "revision": project.revision,
                  "settings": {"lineGap": project.settings.lineGap}, "scenes": []}
    for scene in project.scenes:
        lines = []
        for line in scene.lines:
            record = line.model_dump(include={"id", "characterId", "text", "selectedTakeId", "gapSeconds"})
            record["takes"] = [take.model_dump(include=set(PersistedTake.model_fields)) for take in line.takes]
            lines.append(record)
        projection["scenes"].append({"id": scene.id, "lines": lines})
    source = resolve_motion_source(projection, request.scene_id, request.line_id, audio_available)
    line = next(line for scene in project.scenes if scene.id == request.scene_id
                for line in scene.lines if line.id == request.line_id)
    context = {
        "line": line.model_dump(include=_LINE_INPUTS - {"pronunciations"}, exclude_none=True),
        "settings": project.settings.model_dump(include=_SETTINGS_INPUTS, exclude_none=True),
    }
    if line.pronunciations is not None:
        context["line"]["pronunciations"] = [
            item.model_dump(include={"id", "start", "end", "text", "reading"}) for item in line.pronunciations
        ]
    if source.needs_generation:
        characters = [character for character in project.characters if character.id == source.character_id]
        if len(characters) != 1:
            raise ValueError("Capture generation speaker identity is missing or ambiguous.")
        if generation_environment is None:
            raise ValueError("Capture generation requires reviewed runtime and reference identities.")
        generation_environment.validate()
        context["environment"] = asdict(generation_environment)
        context["dictionary"] = [
            {key: entry.get(key) for key in ("id", "term", "reading", "source", "characterId", "locked") if key in entry}
            for entry in project.pronunciationDictionary or []
        ]
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return PreparationSnapshot(source, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), context)

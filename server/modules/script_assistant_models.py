from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from server.app_deps import Field
from server.modules.request_model import StrictRequestModel
from server.registry import deps


class ScriptAssistantRequest(StrictRequestModel):
    """Project-backed insert or rewrite request that produces a preview."""

    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern="^(ollama|lmstudio|openai|scena-local)$")
    operation: Literal["insert", "rewrite", "paraphrase", "cast-compose"]
    scene_id: str = Field(default="", max_length=120)
    before_line_id: str = Field(default="", max_length=120)
    line_ids: list[str] = Field(default_factory=list, max_length=1000)
    character_ids: list[str] = Field(min_length=1)
    instruction: str = Field(default="", max_length=3000)
    target_kind: Literal["lines", "minutes"] = "lines"
    target_line_count: int = Field(default=1, ge=1, le=1000)
    target_minutes: float = Field(default=0.5, ge=0.5, le=30)
    speech_rate: float = Field(default=1.2, ge=0.5, le=2.0)
    line_gap: float = Field(default=0.7, ge=0, le=9999)
    emoji_expressions: bool = False
    filler_richness: bool = False
    simultaneous_cues: bool = False
    overlapping_speech: bool | None = None
    cast_settings: dict[str, deps.DraftCastSettings] = Field(default_factory=dict)
    performance_speech_rate_min: float = Field(default=0.85, ge=0.5, le=2.0)
    performance_speech_rate_max: float = Field(default=1.35, ge=0.5, le=2.0)
    performance_gap_min: float = Field(default=0, ge=-30, le=9999)
    performance_gap_max: float = Field(default=5, ge=0, le=9999)
    allowed_emojis: list[str] = Field(
        default_factory=lambda: [emoji for emoji, _label, _description in deps.IRODORI_EMOJI_CATALOG], max_length=45,
    )

    @model_validator(mode="after")
    def validate_script_assistant(self) -> "ScriptAssistantRequest":
        if self.overlapping_speech is None:
            self.overlapping_speech = self.simultaneous_cues
        if self.operation == "insert" and (not self.scene_id or self.line_ids):
            raise ValueError("insert requires scene_id and no line_ids")
        if self.operation != "insert" and (not self.line_ids or self.scene_id):
            raise ValueError("rewrite operations require line_ids and no scene_id")
        if len(set(self.character_ids)) != len(self.character_ids) or len(set(self.line_ids)) != len(self.line_ids):
            raise ValueError("line_ids and character_ids must be unique")
        if self.performance_speech_rate_min > self.performance_speech_rate_max:
            raise ValueError("performance speech-rate minimum must not exceed maximum")
        if self.performance_gap_min > self.performance_gap_max:
            raise ValueError("performance gap minimum must not exceed maximum")
        if unsupported := set(self.allowed_emojis) - deps.IRODORI_EMOJIS:
            raise ValueError(f"allowed_emojis contains unsupported emoji: {', '.join(sorted(unsupported))}")
        if not self.overlapping_speech and self.performance_gap_min < 0:
            self.performance_gap_min = 0
        return self


class ScriptAssistantApplyRequest(StrictRequestModel):
    proposal_id: str = Field(min_length=1, max_length=120)
    source_signature: str = Field(min_length=16, max_length=128)
    accepted_row_ids: list[str] = Field(default_factory=list, max_length=1000)
    accepted_group_ids: list[str] = Field(default_factory=list, max_length=1000)


deps.register(__name__, ["ScriptAssistantApplyRequest", "ScriptAssistantRequest"])

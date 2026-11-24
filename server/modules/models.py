from __future__ import annotations

from typing import Any, Literal

from server.app_deps import Field
from pydantic import field_validator, model_validator
from server.modules.image_prompt_models import ImagePromptPreferences
from server.modules.request_model import StrictRequestModel
from server.modules.lora_reference import LoraReference
from server.modules.lora_mix import LoraMix
from server.registry import deps
from server.modules.voice_design import CandidateRequest, VoiceDesignModel, voice_design_keywords  # noqa: F401

LLM_PROVIDER_PATTERN = "^(ollama|lmstudio|openai|scena-local)$"

class ImportVoiceDesignReferenceRequest(StrictRequestModel):
    audio_base64: str = Field(min_length=16, max_length=34952536)
    kind: Literal["baseline", "emotion"] = "baseline"
    emotion: Literal["normal", "joy", "anger", "sorrow", "delight"] | None = None
    reference_candidate_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_voice_design_phase(self) -> "ImportVoiceDesignReferenceRequest":
        if self.kind == "emotion" and (self.emotion is None or not self.reference_candidate_id):
            raise ValueError("Emotion references require an emotion and selected baseline candidate.")
        if self.kind == "baseline" and (self.emotion is not None or self.reference_candidate_id is not None):
            raise ValueError("Baseline references cannot have an emotion or reference candidate.")
        return self


class AcceptCandidateRequest(StrictRequestModel):
    candidate_id: str
    name: str = Field(min_length=1, max_length=80)
    profile: str = Field(default="", max_length=2000)


class SaveVoiceDesignRequest(StrictRequestModel):
    baseline_candidate_id: str = Field(min_length=1, max_length=120)
    emotion_candidate_ids: dict[Literal["normal", "joy", "anger", "sorrow", "delight"], str] = Field(default_factory=dict)
    name: str = Field(min_length=1, max_length=80)
    profile: str = Field(default="", max_length=2000)
    voice_keywords: str = Field(default="", max_length=1000)
    voice_design: VoiceDesignModel | None = None
    character_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_emotion_candidates(self) -> "SaveVoiceDesignRequest":
        if not self.voice_keywords.strip() and (self.voice_design is None or not voice_design_keywords(self.voice_design.model_dump())):
            raise ValueError("VoiceDesign requires voice_keywords or at least one structured field.")
        required = {"normal", "joy", "anger", "sorrow", "delight"}
        if self.emotion_candidate_ids and (set(self.emotion_candidate_ids) != required or not all(self.emotion_candidate_ids.values())):
            raise ValueError("VoiceDesign emotion references require one candidate for each emotion.")
        return self


class ImportReferenceRequest(StrictRequestModel):
    name: str = Field(min_length=1, max_length=80)
    profile: str = Field(default="", max_length=2000)
    audio_base64: str = Field(min_length=16, max_length=34952536)


class UpdateReferenceRequest(StrictRequestModel):
    audio_base64: str = Field(min_length=16, max_length=34952536)


class ApplyCandidateReferenceRequest(StrictRequestModel):
    candidate_id: str = Field(min_length=1, max_length=120)


class UpdateCharacterRequest(StrictRequestModel):
    lora: LoraReference | None = None
    loraMix: LoraMix | None = None
    name: str = Field(min_length=1, max_length=80)
    profile: str = Field(default="", max_length=2000)
    voice_keywords: str = Field(default="", max_length=300)
    profile_details: dict[str, Any] | None = None
    image_prompt: str | None = Field(default=None, max_length=12000)
    image_prompt_preferences: ImagePromptPreferences | None = None


class UpdateCharacterAvatarRequest(StrictRequestModel):
    original_image_base64: str = Field(min_length=32, max_length=12000000)
    thumbnail_image_base64: str = Field(min_length=32, max_length=1200000)


class DraftCastSettings(StrictRequestModel):
    emoji_expressions: bool = False
    filler_richness: bool = False
    appearance_priority: Literal["main", "supporting", "standard"] = "standard"


class DraftRequest(StrictRequestModel):
    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    character_ids: list[str] = Field(min_length=1, max_length=8)
    target_minutes: float = Field(ge=1, le=60)
    theme: str = Field(min_length=1, max_length=4000)
    speech_rate: float = Field(default=1.2, ge=0.5, le=2.0)
    line_gap: float = Field(default=0.7, ge=0, le=9999)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)
    emoji_expressions: bool = False
    filler_richness: bool = False
    simultaneous_cues: bool = False
    overlapping_speech: bool | None = None
    cast_settings: dict[str, DraftCastSettings] = Field(default_factory=dict)
    performance_speech_rate_min: float = Field(default=0.85, ge=0.5, le=2.0)
    performance_speech_rate_max: float = Field(default=1.35, ge=0.5, le=2.0)
    performance_gap_min: float = Field(default=-2.0, ge=-30, le=9999)
    performance_gap_max: float = Field(default=5, ge=0, le=9999)
    allowed_emojis: list[str] = Field(
        default_factory=lambda: [emoji for emoji, _label, _description in deps.IRODORI_EMOJI_CATALOG],
        max_length=45,
    )

    @model_validator(mode="after")
    def validate_performance_constraints(self) -> "DraftRequest":
        if self.overlapping_speech is None:
            self.overlapping_speech = self.simultaneous_cues
        if not self.overlapping_speech and self.performance_gap_min < 0:
            self.performance_gap_min = 0
        if self.performance_speech_rate_min > self.performance_speech_rate_max:
            raise ValueError("performance_speech_rate_min must not exceed performance_speech_rate_max")
        if self.performance_gap_min > self.performance_gap_max:
            raise ValueError("performance_gap_min must not exceed performance_gap_max")
        if unsupported := set(self.allowed_emojis) - deps.IRODORI_EMOJIS:
            raise ValueError(f"allowed_emojis contains unsupported emoji: {', '.join(sorted(unsupported))}")
        return self

    @field_validator("theme")
    @classmethod
    def validate_theme(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("theme must not be blank")
        return value


class AiDirectionRequest(StrictRequestModel):
    """A deliberately small, project-backed request for changing existing lines."""

    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)
    line_ids: list[str] = Field(min_length=1, max_length=500)
    emoji_expressions: bool = True
    cast_settings: dict[str, DraftCastSettings] = Field(default_factory=dict)
    speech_rate: bool = True
    gap_seconds: bool = True
    stage_direction: bool = True
    remove_emoji_expressions: bool = False
    remove_speech_rate: bool = False
    remove_gap_seconds: bool = False
    remove_stage_direction: bool = False
    overwrite_existing: bool = False
    allowed_emojis: list[str] = Field(default_factory=list, max_length=45)
    speech_rate_min: float = Field(default=0.85, ge=0.5, le=2.0)
    speech_rate_max: float = Field(default=1.35, ge=0.5, le=2.0)
    gap_min: float = Field(default=0, ge=-30, le=9999)
    gap_max: float = Field(default=5, ge=0, le=9999)
    allow_negative_gap: bool = Field(default=False, exclude=True)

    @model_validator(mode="after")
    def validate_direction_constraints(self) -> "AiDirectionRequest":
        if not any(
            (
                self.emoji_expressions,
                self.speech_rate,
                self.gap_seconds,
                self.stage_direction,
                self.remove_emoji_expressions,
                self.remove_speech_rate,
                self.remove_gap_seconds,
                self.remove_stage_direction,
            )
        ):
            raise ValueError("Select at least one direction item.")
        conflicting = (
            (self.emoji_expressions, self.remove_emoji_expressions),
            (self.speech_rate, self.remove_speech_rate),
            (self.gap_seconds, self.remove_gap_seconds),
            (self.stage_direction, self.remove_stage_direction),
        )
        if any(add and remove for add, remove in conflicting):
            raise ValueError("A direction item cannot be generated and deleted together.")
        if self.gap_min < 0 and not self.allow_negative_gap:
            raise ValueError("negative gaps are available only to AI drafts with simultaneous cues")
        if self.speech_rate_min > self.speech_rate_max or self.gap_min > self.gap_max:
            raise ValueError("minimum must not exceed maximum")
        if unsupported := set(self.allowed_emojis) - deps.IRODORI_EMOJIS:
            raise ValueError(f"allowed_emojis contains unsupported emoji: {', '.join(sorted(unsupported))}")
        return self


class AiJobRequest(StrictRequestModel):
    """One asynchronous AI job contract for drafting and directing."""

    mode: Literal["draft", "direction"]
    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)

    # Draft-only inputs.
    character_ids: list[str] = Field(default_factory=list, max_length=8)
    target_minutes: float = Field(default=1, ge=1, le=60)
    theme: str = Field(default="", max_length=4000)
    # Draft uses a numeric default; direction accepts the legacy boolean field.
    speech_rate: bool | float = 1.2
    line_gap: float = Field(default=0.7, ge=0, le=9999)
    emoji_expressions: bool = False
    filler_richness: bool = False
    simultaneous_cues: bool = False
    overlapping_speech: bool | None = None
    cast_settings: dict[str, DraftCastSettings] = Field(default_factory=dict)
    performance_speech_rate_min: float = Field(default=0.85, ge=0.5, le=2.0)
    performance_speech_rate_max: float = Field(default=1.35, ge=0.5, le=2.0)
    performance_gap_min: float = Field(default=-2.0, ge=-30, le=9999)
    performance_gap_max: float = Field(default=5, ge=0, le=9999)

    # Direction-only inputs.
    line_ids: list[str] = Field(default_factory=list, max_length=500)
    # This is also the draft's emoji preference; its meaning is mode-specific.
    emoji_expressions: bool = False
    direction_speech_rate: bool | None = None
    gap_seconds: bool = True
    stage_direction: bool = True
    remove_emoji_expressions: bool = False
    remove_speech_rate: bool = False
    remove_gap_seconds: bool = False
    remove_stage_direction: bool = False
    overwrite_existing: bool = False
    allowed_emojis: list[str] = Field(default_factory=list, max_length=45)
    speech_rate_min: float = Field(default=0.85, ge=0.5, le=2.0)
    speech_rate_max: float = Field(default=1.35, ge=0.5, le=2.0)
    gap_min: float = Field(default=0, ge=0, le=9999)
    gap_max: float = Field(default=5, ge=0, le=9999)

    @model_validator(mode="after")
    def validate_job(self) -> "AiJobRequest":
        if self.mode == "draft":
            if isinstance(self.speech_rate, bool):
                raise ValueError("draft speech_rate must be numeric")
            DraftRequest.model_validate(self.model_dump(include=set(DraftRequest.model_fields)))
        else:
            values = self.model_dump(include=set(AiDirectionRequest.model_fields))
            if self.direction_speech_rate is not None:
                values["speech_rate"] = self.direction_speech_rate
            AiDirectionRequest.model_validate(values)
        return self

    def draft_request(self) -> DraftRequest:
        return DraftRequest.model_validate(self.model_dump(include=set(DraftRequest.model_fields)))

    def direction_request(self) -> AiDirectionRequest:
        values = self.model_dump(include=set(AiDirectionRequest.model_fields))
        if self.direction_speech_rate is not None:
            values["speech_rate"] = self.direction_speech_rate
        return AiDirectionRequest.model_validate(values)


class LineAssistantRequest(StrictRequestModel):
    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)
    scene_id: str = Field(min_length=1, max_length=120)
    before_line_id: str = Field(default="", max_length=120)
    character_id: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=2, max_length=3000)
    line_count: int = Field(default=1, ge=1, le=10)
    speech_rate: float = Field(default=1.2, ge=0.5, le=2.0)
    line_gap: float = Field(default=0.7, ge=0, le=9999)
    emoji_expressions: bool = False
    filler_richness: bool = False


class ThemeSuggestionRequest(StrictRequestModel):
    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)
    theme: str = Field(default="", max_length=4000)
    target_minutes: float = Field(default=3, ge=1, le=60)
    character_ids: list[str] = Field(min_length=1, max_length=8)
    cast_settings: dict[str, DraftCastSettings] = Field(default_factory=dict)


class VoiceDesignSuggestionRequest(StrictRequestModel):
    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)
    keywords: str = Field(min_length=3, max_length=1000)
    character_context: str = Field(default="", max_length=8000)


class CharacterProfileSuggestionRequest(StrictRequestModel):
    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)
    mode: Literal["fill_missing", "replace_details"] = "fill_missing"
    scope: Literal["all", "profile", "relations"] = "all"
    name: str = Field(default="", max_length=80)
    profile: str = Field(default="", max_length=2000)
    profile_details: dict[str, Any] = Field(default_factory=dict)
    idea: str = Field(default="", max_length=2000)
    other_casts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class ImagePromptSuggestionRequest(ImagePromptPreferences):
    base_url: str = Field(default="", max_length=400)
    model: str = Field(default="", max_length=160)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)
    name: str = Field(default="", max_length=80)
    profile: str = Field(default="", max_length=2000)
    profile_details: dict[str, Any] = Field(default_factory=dict)


class ModelListRequest(StrictRequestModel):
    base_url: str = Field(min_length=8, max_length=400)
    api_key: str = Field(default="", max_length=500)
    provider: str = Field(default="openai", pattern=LLM_PROVIDER_PATTERN)


class ConnectionSettingsRequest(StrictRequestModel):
    provider: str = Field(default="ollama", pattern=LLM_PROVIDER_PATTERN)
    base_url: str = Field(default="http://127.0.0.1:11434/v1", min_length=8, max_length=400)
    model: str = Field(default="", max_length=160)
    api_key_enabled: bool = False
    api_key: str | None = Field(default=None, max_length=500)
    engine_dir: str = Field(default="", max_length=2000)


class ProjectPatch(StrictRequestModel):
    base_revision: int = Field(alias="baseRevision", ge=0)
    changes: dict[str, Any]


class CharacterOrderRequest(StrictRequestModel):
    base_revision: int = Field(alias="baseRevision", ge=0)
    character_ids: list[str] = Field(alias="characterIds", max_length=200)


class GlobalCastUpdatesRequest(StrictRequestModel):
    character_ids: list[str] = Field(min_length=1, max_length=200)


class ScriptImportLine(StrictRequestModel):
    character_id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=10000)


class ScriptImportRequest(StrictRequestModel):
    lines: list[ScriptImportLine] = Field(min_length=1, max_length=2000)


class GenerateLineRequest(StrictRequestModel):
    quality: str = Field(default="fast", pattern="^(turbo|fast|quality)$")
    mode: Literal["append", "replace"] = "append"
    interruptible: bool = False
    targetTakeId: str | None = None
    seed: int | None = Field(default=None, ge=0, lt=2_000_000_000)


class CancelAutoRenderRequest(StrictRequestModel):
    lineId: str | None = None


class ManualPronunciationEntryRequest(StrictRequestModel):
    term: str = Field(min_length=1, max_length=160)
    reading: str = Field(default="", max_length=160)


class CastPronunciationReadingRequest(StrictRequestModel):
    reading: str = Field(default="", max_length=160)


class PronunciationLockRequest(StrictRequestModel):
    locked: bool


class CastPronunciationEntryRequest(StrictRequestModel):
    character_id: str = Field(min_length=1, max_length=120)
    term: str = Field(min_length=1, max_length=160)
    reading: str = Field(default="", max_length=160)


class PronunciationChangeRequest(StrictRequestModel):
    operation: Literal[
        "add-manual",
        "update-manual",
        "delete-manual",
        "add-cast",
        "update-cast",
        "delete-cast",
        "suggest-manual",
        "suggest-cast",
        "toggle-scope",
    ]
    entry_id: str = Field(default="", max_length=120)
    character_id: str = Field(default="", max_length=120)
    term: str = Field(default="", max_length=160)
    reading: str = Field(default="", max_length=160)
    scope: Literal["global", "project"] = "global"
    scopes: list[Literal["global", "project"]] | None = None
    enabled: bool = True
    replace_conflict: bool = False
    global_id: str = Field(default="", max_length=120)
    project_id: str = Field(default="", max_length=120)
    locked: bool | None = None


class WorkspaceRequest(StrictRequestModel):
    path: str = Field(min_length=1, max_length=8000)


class AddCueMemberRequest(StrictRequestModel):
    character_id: str = Field(min_length=1, max_length=120)


class ChangeLineCharacterRequest(StrictRequestModel):
    character_id: str = Field(min_length=1, max_length=120)


class CastSwitchMapping(StrictRequestModel):
    from_character_id: str = Field(min_length=1, max_length=120)
    to_character_id: str = Field(min_length=1, max_length=120)


class BulkSwitchCharactersRequest(StrictRequestModel):
    mappings: list[CastSwitchMapping] = Field(min_length=1, max_length=200)


deps.register(
    __name__,
    [
        "AcceptCandidateRequest",
        "AddCueMemberRequest",
        "ApplyCandidateReferenceRequest",
        "AiJobRequest",
        "AiDirectionRequest",
        "BulkSwitchCharactersRequest",
        "CastSwitchMapping",
        "CandidateRequest",
        "SaveVoiceDesignRequest",
        "ChangeLineCharacterRequest",
        "CharacterOrderRequest",
        "CharacterProfileSuggestionRequest",
        "ConnectionSettingsRequest",
        "DraftCastSettings",
        "DraftRequest",
        "GenerateLineRequest",
        "CancelAutoRenderRequest",
        "GlobalCastUpdatesRequest",
        "ImportVoiceDesignReferenceRequest",
        "ImagePromptSuggestionRequest",
        "ImportReferenceRequest",
        "LineAssistantRequest",
        "ManualPronunciationEntryRequest",
        "PronunciationChangeRequest",
        "CastPronunciationReadingRequest",
        "CastPronunciationEntryRequest",
        "PronunciationLockRequest",
        "ModelListRequest",
        "ProjectPatch",
        "ScriptImportLine",
        "ScriptImportRequest",
        "ThemeSuggestionRequest",
        "UpdateCharacterAvatarRequest",
        "UpdateCharacterRequest",
        "UpdateReferenceRequest",
        "VoiceDesignSuggestionRequest",
        "WorkspaceRequest",
    ],
)

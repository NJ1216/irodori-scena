from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from server.modules.request_model import StrictRequestModel
from server.modules.lora_reference import LoraReference
from server.modules.lora_mix import LoraMix

from server.registry import deps


class PersistedModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class PersistedTake(PersistedModel):
    lora: LoraReference | None = None
    loraMix: LoraMix | None = None
    loraExecution: dict[str, Any] | None = None
    id: str
    characterId: str | None = None
    audioUrl: str
    seed: int
    quality: Literal["turbo", "fast", "quality"]
    stageDirection: str = ""
    durationSeconds: float | None = None
    targetDurationSeconds: float | None = None
    speechRate: float | None = None
    settings: dict[str, float | int] | None = None
    generationSeconds: float | None = None
    createdAt: int
    renderedText: str | None = None
    ttsConfiguration: dict[str, str | None] | None = None
    ttsPerformance: dict[str, Any] | None = None


class PersistedPronunciation(PersistedModel):
    id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str
    reading: str


class PersistedLine(PersistedModel):
    id: str
    characterId: str
    text: str
    pronunciations: list[PersistedPronunciation] | None = None
    stageDirection: str = ""
    takes: list[PersistedTake] = Field(default_factory=list)
    selectedTakeId: str | None = None
    fixedSeed: int | None = Field(default=None, ge=0)
    manualSeed: int | None = Field(default=None, ge=0, lt=2_000_000_000)
    gapSeconds: float | None = None
    speechRate: float | None = None
    textCfg: float | None = None
    voiceCfg: float | None = None
    captionCfg: float | None = None
    targetDurationSeconds: float | None = None
    enabled: bool | None = None
    cueId: str | None = None
    startOffsetSeconds: float | None = Field(default=None, ge=0)


class PersistedScene(PersistedModel):
    id: str
    title: str
    lines: list[PersistedLine]


class PersistedCharacter(PersistedModel):
    sampleText: str | None = None
    lora: LoraReference | None = None
    loraMix: LoraMix | None = None
    id: str
    name: str
    profile: str = ""
    profileDetails: dict[str, Any] | None = None
    voiceKeywords: str = ""
    voiceDesign: dict[str, Any] | None = None
    imagePrompt: str | None = None
    imagePromptPreferences: dict[str, Any] | None = None
    avatarOriginalUrl: str | None = None
    avatarThumbnailUrl: str | None = None
    avatarUrl: str | None = None
    avatarVersion: int | None = None
    referenceVersion: int | None = None
    referenceAudioUrl: str
    referenceFile: str
    createdAt: int


class PersistedCandidate(PersistedModel):
    id: str
    keywords: str
    voiceDesign: dict[str, Any] | None = None
    sampleText: str
    seed: int
    audioUrl: str
    file: str
    createdAt: int
    durationSeconds: float | None = None
    kind: Literal["baseline", "emotion"] | None = None
    emotion: Literal["normal", "joy", "anger", "sorrow", "delight"] | None = None
    referenceCandidateId: str | None = None
    speechRate: float | None = None
    textCfg: float | None = None
    voiceCfg: float | None = None
    captionCfg: float | None = None


class PersistedSettings(PersistedModel):
    speechRate: float
    steps: int
    textCfg: float
    voiceCfg: float
    captionCfg: float | None = None
    seed: int
    quality: Literal["turbo", "fast", "quality"]
    lineGap: float | None = None
    llmBaseUrl: str
    llmModel: str
    emojiExpressions: bool | None = None
    fillerRichness: bool | None = None


class StudioProjectModel(PersistedModel):
    version: int = 1
    revision: int = Field(default=0, ge=0)
    id: str
    title: str
    characters: list[PersistedCharacter]
    candidates: list[PersistedCandidate]
    scenes: list[PersistedScene]
    settings: PersistedSettings
    ttsSelection: dict[str, Any] | None = None
    scriptCastContexts: dict[str, dict[str, str]] | None = None
    pronunciationDictionary: list[dict[str, Any]] | None = None


class LineGenerationResponse(BaseModel):
    take: PersistedTake
    projectRevision: int = Field(ge=0)


class ProjectUpdate(StrictRequestModel):
    project: StudioProjectModel
    base_revision: int | None = Field(default=None, alias="baseRevision", ge=0)


deps.register(__name__, ["LineGenerationResponse", "ProjectUpdate", "StudioProjectModel"])

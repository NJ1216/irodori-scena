from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from server.modules.request_model import StrictRequestModel
from server.modules.constants import VOICE_SAMPLE_TEXT

VOICE_DESIGN_AUDIO_QUALITY_SUFFIX = "コンデンサーマイクで近接収録したような、クリアで明瞭な音質。"
VOICE_DESIGN_OPTIONS = {
    "AGE": (
        "小学校低学年",
        "小学校高学年",
        "中学生",
        "高校生",
        "大学生",
        "20代",
        "30代",
        "40代",
        "50代",
        "60代",
        "初老",
        "長老",
    ),
    "GENDER": ("男児", "女児", "男の子", "女の子", "男性", "女性", "中性"),
    "PITCH": {"かなり低い", "低い", "やや低い", "やや高い", "高い", "かなり高い"},
    "STYLE": {
        "優しい",
        "穏やか",
        "快活",
        "落ち着いた",
        "淡々とした",
        "上品",
        "力強い",
        "威厳のある",
        "色気のある",
        "無邪気",
        "幼い",
        "ささやくような",
        "舌足らず",
        "歯切れがよい",
        "冷たい",
        "気だるい",
        "感情豊か",
        "おっとり",
    },
    "QUALITY": {
        "ハスキー",
        "かすれた",
        "艶のある",
        "透明感のある",
        "甘い",
        "乾いた",
        "ざらついた",
        "金属的",
        "太い",
        "細い",
        "軽い",
        "重厚",
        "息を多く含む",
        "息が少ない",
        "鼻にかかった",
        "胸に響く",
        "こもった",
        "よく通る",
    },
}


class VoiceDesignModel(BaseModel):
    age: (
        Literal[
            "小学校低学年",
            "小学校高学年",
            "中学生",
            "高校生",
            "大学生",
            "20代",
            "30代",
            "40代",
            "50代",
            "60代",
            "初老",
            "長老",
        ]
        | None
    ) = None
    gender: Literal["男児", "女児", "男の子", "女の子", "男性", "女性", "中性"] | None = None
    pitch: Literal["かなり低い", "低い", "やや低い", "やや高い", "高い", "かなり高い"] | None = None
    qualities: list[
        Literal[
            "ハスキー",
            "かすれた",
            "艶のある",
            "透明感のある",
            "甘い",
            "乾いた",
            "ざらついた",
            "金属的",
            "太い",
            "細い",
            "軽い",
            "重厚",
            "息を多く含む",
            "息が少ない",
            "鼻にかかった",
            "胸に響く",
            "こもった",
            "よく通る",
        ]
    ] = Field(default_factory=list, max_length=18)
    style: (
        Literal[
            "優しい",
            "穏やか",
            "快活",
            "落ち着いた",
            "淡々とした",
            "上品",
            "力強い",
            "威厳のある",
            "色気のある",
            "無邪気",
            "幼い",
            "ささやくような",
            "舌足らず",
            "歯切れがよい",
            "冷たい",
            "気だるい",
            "感情豊か",
            "おっとり",
        ]
        | None
    ) = None
    notes: str = Field(default="", max_length=600)

    @field_validator("gender", mode="before")
    @classmethod
    def normalize_legacy_gender(cls, value: object) -> object:
        return "中性" if value == "中性的" else value


class CandidateRequest(StrictRequestModel):
    keywords: str = Field(default="", max_length=1000)
    count: int = Field(default=3, ge=1, le=10)
    sample_text: str = Field(default=VOICE_SAMPLE_TEXT, min_length=5, max_length=240)
    kind: Literal["baseline", "emotion"] = "baseline"
    emotion: Literal["normal", "joy", "anger", "sorrow", "delight"] | None = None
    reference_candidate_id: str | None = Field(default=None, max_length=120)
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)
    text_cfg: float = Field(default=3.0, ge=0.0, le=10.0)
    voice_cfg: float = Field(default=5.0, ge=0.0, le=10.0)
    caption_cfg: float = Field(default=3.0, ge=0.0, le=10.0)
    voice_design: VoiceDesignModel | None = None

    @model_validator(mode="after")
    def validate_voice_design_phase(self) -> "CandidateRequest":
        if not self.keywords.strip() and (
            self.voice_design is None or not voice_design_keywords(self.voice_design.model_dump())
        ):
            raise ValueError("VoiceDesign requires keywords or at least one structured field.")
        if self.kind == "emotion" and (self.emotion is None or not self.reference_candidate_id):
            raise ValueError("Emotion candidates require an emotion and selected baseline candidate.")
        if self.kind == "baseline" and (self.emotion is not None or self.reference_candidate_id is not None):
            raise ValueError("Baseline candidates cannot have a reference candidate.")
        return self


def _field_text(item: Any) -> str:
    return "" if item is None else str(item).strip()


def voice_design_keywords(value: dict[str, Any]) -> str:
    parts = []
    for key, suffix in (("age", "の声"), ("gender", "の声"), ("pitch", "声")):
        if item := _field_text(value.get(key)):
            parts.append(f"{item}{suffix}")
    parts.extend(
        f"{item}{'な' if item == 'ハスキー' else ''}声質"
        for item in map(_field_text, value.get("qualities") or [])
        if item
    )
    if item := _field_text(value.get("style")):
        parts.append(f"{item}話し方")
    if notes := _field_text(value.get("notes")):
        parts.append(notes)
    return "".join(f"{part.rstrip('。')}。" for part in parts)


def inference_caption(keywords: str) -> str:
    user_caption = keywords.strip().replace(VOICE_DESIGN_AUDIO_QUALITY_SUFFIX, "").strip()
    separator = "" if not user_caption or user_caption.endswith(("。", "！", "？", "!", "?", "、", ",")) else "。"
    return f"{user_caption}{separator}{VOICE_DESIGN_AUDIO_QUALITY_SUFFIX}"


def selected_voice_design_candidates(project: dict[str, Any], request: Any) -> list[dict[str, Any]]:
    by_id = {str(item.get("id", "")): item for item in project.get("candidates", [])}
    baseline = by_id.get(request.baseline_candidate_id)
    if baseline is None or baseline.get("kind", "baseline") != "baseline":
        raise HTTPException(status_code=422, detail="選択した基準ボイスが見つかりません。")
    clips = [baseline]
    for emotion, candidate_id in request.emotion_candidate_ids.items():
        candidate = by_id.get(candidate_id)
        if (
            candidate is None
            or candidate.get("kind") != "emotion"
            or candidate.get("emotion") != emotion
            or candidate.get("referenceCandidateId") != baseline["id"]
        ):
            raise HTTPException(
                status_code=422, detail="基準ボイスを参照した5種類すべての感情クリップを選んでください。"
            )
        clips.append(candidate)
    return clips

"""Internal immutable media proposals and bounded PCM/LAB consistency checks."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import wave
from typing import Any

from server.modules.motion_source import MotionSource, motion_content_version


@dataclass(frozen=True)
class PreparationRequest:
    operation_id: str
    project_id: str
    scene_id: str
    line_id: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not value.strip() for value in (
            self.operation_id, self.project_id, self.scene_id, self.line_id,
        )):
            raise ValueError("Preparation requires nonempty operation and source identities.")


@dataclass(frozen=True)
class PreparationSnapshot:
    source: MotionSource
    inputs_identity: str
    generation_inputs: Any = None


@dataclass(frozen=True)
class ProposedAudio:
    take_id: str
    wav: bytes


@dataclass(frozen=True)
class ProposedLab:
    content: bytes
    wav_sha256: str
    analysis_identity: str


@dataclass(frozen=True)
class PreparedBundle:
    snapshot: PreparationSnapshot
    audio: ProposedAudio
    lab: ProposedLab
    dialogue_txt: bytes
    wav_sha256: str
    frame_count: int
    sample_rate: int
    content_version: str


def wav_details(wav: bytes) -> tuple[int, int, str]:
    if not isinstance(wav, bytes):
        raise ValueError("Prepared WAV must be immutable bytes.")
    try:
        with wave.open(BytesIO(wav), "rb") as reader:
            frames, rate = reader.getnframes(), reader.getframerate()
            width, channels = reader.getsampwidth(), reader.getnchannels()
            if min(frames, rate, width, channels) <= 0 or reader.getcomptype() != "NONE":
                raise ValueError("Prepared WAV has no playable PCM frames.")
            reader.setpos(frames - 1)
            if len(reader.readframes(1)) != width * channels:
                raise ValueError("Prepared WAV PCM is truncated.")
    except (EOFError, wave.Error) as error:
        raise ValueError("Prepared WAV is invalid.") from error
    return frames, rate, hashlib.sha256(wav).hexdigest()


def validate_lab(content: bytes, frame_count: int, sample_rate: int) -> None:
    """Current internal Rhubarb labels and continuous 10,000,000-tick rows only."""
    if not isinstance(content, bytes):
        raise ValueError("Prepared LAB must be immutable UTF-8 bytes.")
    duration = round(frame_count * 10_000_000 / sample_rate)
    cursor = 0
    try:
        rows = content.decode("utf-8").splitlines()
        if not rows:
            raise ValueError("Prepared LAB is empty.")
        for row in rows:
            start, end, label = row.split()
            if not start.isdecimal() or not end.isdecimal():
                raise ValueError("Prepared LAB times must be nonnegative integer ticks.")
            start, end = int(start), int(end)
            if start != cursor or end <= start or end > duration or label not in {"a", "i", "u", "e", "o", "N", "pau"}:
                raise ValueError("Prepared LAB rows are not continuous valid source intervals.")
            cursor = end
        if cursor != duration:
            raise ValueError("Prepared LAB does not cover the exact WAV duration.")
    except (UnicodeError, ValueError) as error:
        raise ValueError("Prepared LAB is invalid.") from error


def assemble_bundle(snapshot: PreparationSnapshot, audio: ProposedAudio, lab: ProposedLab) -> PreparedBundle:
    frames, rate, digest = wav_details(audio.wav)
    validate_lab(lab.content, frames, rate)
    version = motion_content_version(
        snapshot.source, take_id=audio.take_id, wav_sha256=digest,
        lab_sha256=hashlib.sha256(lab.content).hexdigest(), lab_wav_sha256=lab.wav_sha256,
        analysis_identity=lab.analysis_identity,
    )
    return PreparedBundle(snapshot, audio, lab, snapshot.source.body.encode("utf-8"), digest, frames, rate, version)

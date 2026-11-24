from __future__ import annotations

from server.app_deps import io, wave, Path, HTTPException
from server.registry import deps

MAX_REFERENCE_SECONDS = 120.0
REFERENCE_CLIP_GAP_SECONDS = 0.7


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as source:
            if source.getcomptype() != "NONE" or source.getframerate() <= 0:
                raise ValueError
            return source.getnframes() / source.getframerate()
    except (wave.Error, EOFError, ValueError) as error:
        raise HTTPException(status_code=422, detail="VoiceDesign候補のWAV形式または長さが不正です。") from error


def _read_wav(path: Path) -> tuple[tuple[int, int, int, int, str, str], bytes]:
    try:
        with wave.open(str(path), "rb") as source:
            params = source.getparams()
            if params.comptype != "NONE" or params.framerate <= 0 or params.sampwidth not in {1, 2, 3, 4}:
                raise ValueError
            return (params.nchannels, params.sampwidth, params.framerate, params.nframes, params.comptype, params.compname), source.readframes(params.nframes)
    except (wave.Error, EOFError, ValueError) as error:
        raise HTTPException(status_code=422, detail="VoiceDesign候補のWAV形式または長さが不正です。") from error


def concatenate_reference_wavs(paths: list[Path]) -> bytes:
    """Join compatible PCM WAVs with 0.7-second gaps, retaining no more than 120 seconds."""
    if not paths:
        raise HTTPException(status_code=422, detail="基準ボイスと5種類の感情クリップを選んでください。")
    decoded = [_read_wav(path) for path in paths]
    format_key = decoded[0][0][:3]
    if any(params[:3] != format_key for params, _audio in decoded[1:]):
        raise HTTPException(status_code=422, detail="VoiceDesign候補のWAV形式が一致しません。候補を作り直してください。")
    channels, width, rate = format_key
    max_frames = int(MAX_REFERENCE_SECONDS * rate)
    gap_frames = round(REFERENCE_CLIP_GAP_SECONDS * rate)
    frames = bytearray()
    used = 0
    for index, (params, audio) in enumerate(decoded):
        if index and used < max_frames:
            gap = min(gap_frames, max_frames - used - 1)
            if gap > 0:
                frames.extend(b"\0" * gap * channels * width)
                used += gap
        available = min(params[3], max_frames - used)
        if available <= 0:
            break
        frames.extend(audio[: available * channels * width])
        used += available
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setparams((channels, width, rate, used, "NONE", "not compressed"))
        target.writeframes(bytes(frames))
    return output.getvalue()


# Irodori-TTS v4.1 cannot generate more than 30 seconds in one pass (max_seconds).
MAX_VOICE_DESIGN_CLIP_SECONDS = 30.0


def validate_voice_design_clip(path: Path) -> float:
    duration = wav_duration(path)
    if duration > MAX_VOICE_DESIGN_CLIP_SECONDS:
        raise HTTPException(
            status_code=422,
            detail={"code": "voice_design_clip_too_long", "message": "VoiceDesignの各クリップは30秒以内にしてください。"},
        )
    return duration


deps.register(__name__, ["concatenate_reference_wavs", "validate_voice_design_clip", "wav_duration"])

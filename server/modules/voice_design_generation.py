"""Generate VoiceDesign candidates while catching audition lines truncated at the model ceiling."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from server.modules.voice_reference import MAX_VOICE_DESIGN_CLIP_SECONDS

# Irodori-TTS clamps the predicted length to its 30-second ceiling, so a clip this close to it
# means the audition line did not fit and its end was cut off.
_CEILING_TOLERANCE_SECONDS = 0.25
SAMPLE_TOO_LONG_DETAIL = {
    "code": "voice_design_sample_too_long",
    "message": "試聴台詞が長すぎて、30秒以内の音声に収まりません。試聴台詞を短くしてから、もう一度お試しください。",
}


def generate_candidate_clips(
    generate: Callable[..., list[Path]],
    measure: Callable[[Path], float],
    discard: Callable[[list[Path]], None],
    *,
    output: Path,
    seed: int,
    count: int,
    **settings: Any,
) -> list[tuple[Path, float]]:
    """Generate one candidate first; stop before the rest when it reached the length ceiling."""
    suffix = output.suffix or ".wav"
    produced: list[Path] = []
    try:
        produced += generate(output=output.with_name(f"{output.stem}_001{suffix}"), seed=seed, num_candidates=1, **settings)
        first = measure(produced[0])
        if first >= MAX_VOICE_DESIGN_CLIP_SECONDS - _CEILING_TOLERANCE_SECONDS:
            raise HTTPException(status_code=422, detail=SAMPLE_TOO_LONG_DETAIL)
        clips = [(produced[0], first)]
        if count > 1:
            rest = generate(
                output=output.with_name(f"{output.stem}_rest{suffix}"), seed=seed + 1, num_candidates=count - 1, **settings
            )
            produced += rest
            clips += [(path, measure(path)) for path in rest]
        return clips
    except Exception:
        discard(produced)
        raise

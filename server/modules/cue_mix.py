from __future__ import annotations

import hashlib
import json
import os
import threading
import wave
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from server.registry import deps
from server.native_processing import mix_pcm_members_wav


MIX_ALGORITHM_VERSION = "cue-mix-v3"
TRUE_PEAK_LIMIT = 10 ** (-1 / 20)
_MIX_LOCKS: dict[str, threading.Lock] = {}
_MIX_LOCKS_GUARD = threading.Lock()
_AUDIO_IDENTITIES: dict[tuple[str, int, int], str] = {}
_AUDIO_IDENTITIES_GUARD = threading.Lock()
_AUDIO_IDENTITIES_LOADED = False


def _identity_index_path() -> Path:
    return deps.DATA_ROOT / "cache" / "audio-identities.json"


def _load_audio_identities() -> None:
    global _AUDIO_IDENTITIES_LOADED
    if _AUDIO_IDENTITIES_LOADED:
        return
    try:
        records = json.loads(_identity_index_path().read_text(encoding="utf-8"))
        for record in records if isinstance(records, list) else []:
            key = (str(record["path"]), int(record["size"]), int(record["mtimeNs"]))
            _AUDIO_IDENTITIES[key] = str(record["sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        _AUDIO_IDENTITIES.clear()
    _AUDIO_IDENTITIES_LOADED = True


def _save_audio_identities() -> None:
    path = _identity_index_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    records = [
        {"path": key[0], "size": key[1], "mtimeNs": key[2], "sha256": value} for key, value in _AUDIO_IDENTITIES.items()
    ]
    try:
        temporary.write_text(json.dumps(records, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _mix_lock(signature: str) -> threading.Lock:
    with _MIX_LOCKS_GUARD:
        return _MIX_LOCKS.setdefault(signature, threading.Lock())


def audio_file_identity(path: Path) -> str:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    with _AUDIO_IDENTITIES_GUARD:
        _load_audio_identities()
        cached = _AUDIO_IDENTITIES.get(key)
    if cached is not None:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    identity = digest.hexdigest()
    with _AUDIO_IDENTITIES_GUARD:
        stale = [candidate for candidate in _AUDIO_IDENTITIES if candidate[0] == key[0] and candidate != key]
        for candidate in stale:
            _AUDIO_IDENTITIES.pop(candidate, None)
        _AUDIO_IDENTITIES[key] = identity
        _save_audio_identities()
    return identity


def mix_pcm_members(members: list[tuple[Path, float]], output: Path) -> float:
    return mix_pcm_members_wav(members, output)


def cue_mix_signature(cue: list[dict[str, Any]]) -> str:
    records = []
    for line in cue:
        take = deps.selected_take_record(line)
        if not take:
            raise HTTPException(status_code=422, detail="同時発話の全メンバーでテイクを選択してください。")
        path = deps.take_audio_path(take)
        records.append(
            {
                "lineId": line.get("id"),
                "takeId": take.get("id"),
                "createdAt": take.get("createdAt"),
                "audioSha256": audio_file_identity(path),
                "offset": deps.normalize_start_offset(line.get("startOffsetSeconds")),
            }
        )
    payload = json.dumps(
        {"algorithm": MIX_ALGORITHM_VERSION, "members": records}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def render_cue_mix(scene: dict[str, Any], line_id: str) -> dict[str, Any]:
    cue = deps.cue_for_line(scene, line_id)
    cue_id = deps.cue_key(cue[0]) if cue else ""
    if len(cue) < 2 or not cue_id:
        raise HTTPException(status_code=422, detail="対象は同時発話キューではありません。")
    signature = cue_mix_signature(cue)
    output = deps.MEDIA_ROOT / "cache" / "cue-mixes" / f"{signature}.wav"
    with _mix_lock(signature):
        if output.is_file():
            with wave.open(str(output), "rb") as reader:
                duration = reader.getnframes() / reader.getframerate()
        else:
            members = [
                (
                    deps.take_audio_path(deps.selected_take_record(line) or {}),
                    deps.normalize_start_offset(line.get("startOffsetSeconds")),
                )
                for line in cue
            ]
            duration = mix_pcm_members(members, output)
        deps.persist_derived_cache(output)
    return {
        "audioUrl": deps.media_url(output),
        "durationSeconds": round(duration, 3),
        "cueId": cue_id,
        "signature": signature,
    }


deps.register(
    __name__,
    [
        "MIX_ALGORITHM_VERSION",
        "audio_file_identity",
        "cue_mix_signature",
        "mix_pcm_members",
        "render_cue_mix",
    ],
)

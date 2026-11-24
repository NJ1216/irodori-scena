from __future__ import annotations

from server.app_deps import os, wave, Path, Any
from server.registry import deps


def validate_take_wav(path: Path) -> float:
    """Validate the WAV header and the final declared PCM frame."""
    try:
        with wave.open(str(path), "rb") as audio:
            channels = audio.getnchannels()
            sample_width = audio.getsampwidth()
            frame_rate = audio.getframerate()
            frame_count = audio.getnframes()
            if channels <= 0 or sample_width <= 0 or frame_rate <= 0 or frame_count <= 0:
                raise ValueError("WAV has no playable PCM frames.")
            if audio.getcomptype() != "NONE":
                raise ValueError("WAV compression is unsupported.")
            audio.setpos(frame_count - 1)
            if len(audio.readframes(1)) != channels * sample_width:
                raise ValueError("WAV PCM data is truncated.")
    except (OSError, EOFError, ValueError, wave.Error) as error:
        raise ValueError(f"Invalid take WAV: {path.name}") from error
    return frame_count / frame_rate


def _managed_take_path(take: dict[str, Any]) -> tuple[bool, Path | None]:
    audio_url = deps.canonical_project_media_url(str(take.get("audioUrl", "")))
    if not audio_url.startswith("/media/takes/"):
        return False, None
    takes_root = (deps.MEDIA_ROOT / "takes").resolve()
    candidate = (deps.MEDIA_ROOT / audio_url.removeprefix("/media/")).resolve()
    try:
        candidate.relative_to(takes_root)
    except ValueError:
        return True, None
    return True, candidate


def _repair_take_list(raw: Any) -> tuple[list[dict[str, Any]], int]:
    retained: list[dict[str, Any]] = []
    removed = 0
    for take in raw if isinstance(raw, list) else []:
        if not isinstance(take, dict):
            removed += 1
            continue
        managed, path = _managed_take_path(take)
        if not managed:
            retained.append(take)
            continue
        if path is None or path.is_symlink() or path.name.startswith(".partial-"):
            if path is not None:
                path.unlink(missing_ok=True)
            removed += 1
            continue
        if not path.exists() and take.get("id") and take.get("seed") is not None:
            # Keep a valid persisted recipe so export can recreate this exact take.
            retained.append(take)
            continue
        try:
            validate_take_wav(path)
        except ValueError:
            path.unlink(missing_ok=True)
            removed += 1
            continue
        retained.append(take)
    return retained, removed


def _project_lines(project: dict[str, Any]):
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []) if isinstance(scene, dict) else []:
            if isinstance(line, dict):
                yield line


def _repair_take_records(project: dict[str, Any]) -> int:
    removed = 0
    for line in _project_lines(project):
        for key in ("takes", "archivedTakes"):
            if key not in line:
                continue
            line[key], count = _repair_take_list(line.get(key))
            removed += count
            if key == "archivedTakes" and not line[key]:
                line.pop(key)
        take_ids = [str(take.get("id", "")) for take in line.get("takes", [])]
        if line.get("selectedTakeId") not in take_ids:
            line["selectedTakeId"] = take_ids[-1] if take_ids else None
    return removed


def _referenced_take_paths(project: dict[str, Any]) -> set[Path]:
    referenced: set[Path] = set()
    for line in _project_lines(project):
        for key in ("takes", "archivedTakes"):
            for take in line.get(key, []) if isinstance(line.get(key), list) else []:
                managed, path = _managed_take_path(take) if isinstance(take, dict) else (False, None)
                if managed and path is not None:
                    referenced.add(path)
    return referenced


def _prune_take_tree(takes_root: Path, referenced: set[Path]) -> None:
    if takes_root.is_dir():
        for directory, directory_names, file_names in os.walk(takes_root, topdown=False, followlinks=False):
            parent = Path(directory)
            for name in file_names:
                path = parent / name
                if path.is_symlink() or path.resolve() not in referenced:
                    path.unlink(missing_ok=True)
            for name in directory_names:
                path = parent / name
                if path.is_symlink():
                    path.unlink(missing_ok=True)
                else:
                    try:
                        path.rmdir()
                    except OSError:
                        pass


def repair_project_take_wavs(project: dict[str, Any]) -> int:
    """Repair managed take records and remove files not owned by any record."""
    removed = _repair_take_records(project)
    takes_root = (deps.MEDIA_ROOT / "takes").resolve()
    _prune_take_tree(takes_root, _referenced_take_paths(project))
    return removed


deps.register(__name__, ["repair_project_take_wavs", "validate_take_wav"])

"""Reconcile disposable project media with the current project graph."""

from server.app_deps import Path, Any, HTTPException
from server.registry import deps


def _cue_mix_signatures(project: dict[str, Any]) -> set[str]:
    signatures: set[str] = set()
    for scene in project.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        for cue in deps.cue_groups(scene.get("lines", [])):
            if len(cue) < 2 or not deps.cue_key(cue[0]):
                continue
            try:
                signatures.add(deps.cue_mix_signature(cue))
            except (OSError, ValueError, RuntimeError, HTTPException):
                continue
    return signatures


def _prune_cache_directory(directory: Path, retained: set[str]) -> None:
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.is_file() or path.is_symlink():
            keep = not path.is_symlink() and path.suffix.lower() == ".wav" and path.stem in retained
            if keep:
                try:
                    deps.validate_take_wav(path)
                except ValueError:
                    keep = False
            if not keep:
                path.unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        pass


def reconcile_project_media(project: dict[str, Any]) -> int:
    """Repair takes and discard mix caches that current selections cannot use."""
    repaired = deps.repair_project_take_wavs(project)
    cache_root = deps.MEDIA_ROOT / "cache"
    _prune_cache_directory(cache_root / "cue-mixes", _cue_mix_signatures(project))
    _prune_cache_directory(cache_root / "overlap-mixes", deps.overlap_cache_signatures(project))
    try:
        cache_root.rmdir()
    except OSError:
        pass
    return repaired


deps.register(__name__, ["reconcile_project_media"])

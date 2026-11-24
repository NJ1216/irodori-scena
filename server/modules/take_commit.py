from __future__ import annotations

from server.app_deps import shutil, Path, Any
from server.registry import deps


def take_rollback_copy(line_id: str, take_id: str) -> tuple[Path, Path] | None:
    target = deps.MEDIA_ROOT / "takes" / deps.safe_segment(line_id) / f"{deps.safe_segment(take_id)}.wav"
    if not target.is_file():
        return None
    backup = target.with_name(f".{target.name}-{deps.new_id('rollback')}.bak")
    try:
        shutil.copy2(target, backup)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    return target, backup


def finish_take_replacement(rollback: tuple[Path, Path] | None, *, restore: bool) -> None:
    if rollback is None:
        return
    target, backup = rollback
    if restore and backup.is_file():
        backup.replace(target)
    backup.unlink(missing_ok=True)


def discard_generated_take(take: dict[str, Any]) -> None:
    url = str(take.get("audioUrl", ""))
    if not url.startswith("/media/"):
        return
    candidate = (deps.MEDIA_ROOT / url.removeprefix("/media/")).resolve()
    try:
        candidate.relative_to(deps.MEDIA_ROOT.resolve())
    except ValueError:
        return
    candidate.unlink(missing_ok=True)


deps.register(__name__, ["discard_generated_take", "finish_take_replacement", "take_rollback_copy"])

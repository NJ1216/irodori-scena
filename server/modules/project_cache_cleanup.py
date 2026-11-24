"""Reclaim unreachable project entries only after a saved project is loaded."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path, PurePosixPath

from server.modules import project_container
from server.modules.project_cache_storage import SCRATCH_PROVENANCE, compact_container_entries
from server.registry import deps


def _media_name(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("/media/"):
        return None
    name = value.lstrip("/")
    try:
        project_container._safe_path(name)
    except Exception:
        return None
    return name


def _referenced_media(project: dict) -> set[str]:
    retained = {"project.json"}
    for character in project.get("characters", []):
        if not isinstance(character, dict):
            continue
        for key in ("referenceAudioUrl", "avatarUrl", "avatarOriginalUrl", "avatarThumbnailUrl"):
            name = _media_name(character.get(key))
            if name:
                retained.add(name)
    for scene in project.get("scenes", []):
        if not isinstance(scene, dict):
            continue
        for line in scene.get("lines", []):
            if not isinstance(line, dict):
                continue
            for key in ("takes", "archivedTakes"):
                for take in line.get(key, []) if isinstance(line.get(key), list) else []:
                    if isinstance(take, dict):
                        name = _media_name(take.get("audioUrl"))
                        if name:
                            retained.add(name)
    return retained


def _scratch_provenance(root: Path) -> list[tuple[str, str, int, int, str]]:
    try:
        records = json.loads((root / SCRATCH_PROVENANCE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(records, dict):
        return []
    result = []
    for path, fields in records.items():
        if not isinstance(path, str) or not path.startswith("media/cache/timeline-v1/"):
            continue
        if not isinstance(fields, list) or len(fields) != 4:
            continue
        plan_id, start, end, targets = fields
        if isinstance(plan_id, str) and isinstance(start, int) and isinstance(end, int):
            result.append((path, plan_id, start, end, json.dumps(targets)))
    return result


def _cache_names(
    project: dict, available: set[str], container: Path,
    scratch_rows: list[tuple[str, str, int, int, str]],
) -> set[str]:
    if not any(scene.get("lines") for scene in project.get("scenes", []) if isinstance(scene, dict)):
        return set()
    retained: set[str] = set()
    cue_dir = "media/cache/cue-mixes/"
    if any(name.startswith(cue_dir) for name in available):
        for scene in project.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            for cue in deps.cue_groups(scene.get("lines", [])):
                if len(cue) > 1 and deps.cue_key(cue[0]):
                    try:
                        retained.add(f"{cue_dir}{deps.cue_mix_signature(cue)}.wav")
                    except Exception:
                        pass
    if any(name.startswith("media/cache/overlap-mixes/") for name in available):
        retained.update(f"media/cache/overlap-mixes/{key}.wav" for key in deps.overlap_cache_signatures(project))
    return retained & available


def _with_parent_directories(names: set[str]) -> set[str]:
    result = set(names)
    for name in names:
        parent = PurePosixPath(name).parent
        while parent != PurePosixPath("."):
            result.add(parent.as_posix())
            parent = parent.parent
    return result


def _prune_working_tree(root: Path, retained: set[str]) -> None:
    for relative, path, kind in project_container._iter_paths(root):
        if kind == "file" and relative.as_posix() not in retained:
            path.unlink(missing_ok=True)
    for directory in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if directory.is_dir() and directory != root:
            try:
                directory.rmdir()
            except OSError:
                pass


def _clear_old_staging(container: Path) -> None:
    prefix = f".{container.name}.staging-"
    for path in container.parent.iterdir():
        if path.is_file() and path.name.startswith(prefix) and path.name != container.name:
            suffix = path.name[len(prefix):]
            marker = suffix.removesuffix("-journal")
            if marker.isdigit() or (len(marker) == 32 and all(c in "0123456789abcdef" for c in marker)):
                path.unlink(missing_ok=True)


def _retained_names(project: dict, container: Path, root: Path, available: set[str]) -> tuple[set[str], list]:
    scratch_rows = _scratch_provenance(root)
    candidates = _referenced_media(project) | _cache_names(project, available, container, scratch_rows)
    retained = _with_parent_directories({name for name in candidates if (root / name).is_file()})
    return retained, [row for row in scratch_rows if row[0] in retained]


def project_optimization_available(project: dict) -> bool:
    container = deps.ACTIVE_PROJECT_PATH
    if container is None:
        return False
    with closing(project_container._connect(container, readonly=True)) as connection:
        if int(connection.execute("PRAGMA freelist_count").fetchone()[0]) > 0:
            return True
        available = {row[0] for row in connection.execute("SELECT path FROM entries")}
    retained, _rows = _retained_names(project, container, deps.ACTIVE_PROJECT_ROOT, available)
    return not available <= retained


def cleanup_loaded_project(project: dict) -> None:
    container = deps.ACTIVE_PROJECT_PATH
    if container is None:
        return
    root = deps.ACTIVE_PROJECT_ROOT
    with closing(project_container._connect(container, readonly=True)) as connection:
        rows = connection.execute("SELECT path, kind, sha256 FROM entries").fetchall()
    available = {row[0] for row in rows}
    retained, preserved_rows = _retained_names(project, container, root, available)
    changed = compact_container_entries(container, retained, preserved_rows)
    _prune_working_tree(root, retained)
    if changed:
        with closing(project_container._connect(container, readonly=True)) as connection:
            files = connection.execute("SELECT path, sha256 FROM entries WHERE kind='file'").fetchall()
        index = {
            name: project_container._file_metadata(root / name, digest)
            for name, digest in files if (root / name).is_file()
        }
        project_container._refresh_sync_index(container, root, index)
    _clear_old_staging(container)


deps.register(__name__, ["cleanup_loaded_project", "project_optimization_available"])

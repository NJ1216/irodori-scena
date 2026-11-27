"""Session-only undo journals for project JSON and owned media boundaries."""

from __future__ import annotations

import asyncio
import os

import anyio
from uuid import UUID

from server.app_deps import hashlib, json, shutil, threading, time, uuid4, Path, Any, HTTPException
from server.modules.history_coalescing import coalesce_auto_render, coalesce_generation_group, prune_unreferenced_blobs
from server.modules.history_pending import PendingCaptures
from server.modules.pronunciation_dictionary import DICTIONARY_LOCK
from server.modules.history_targets import batch_delete_media_targets as _batch_delete_media_targets
from server.modules.history_targets import line_delete_media_targets as _line_delete_media_targets
from server.modules.history_targets import line_take_media_targets as _line_take_media_targets
from server.modules.history_targets import scene_delete_media_targets as _scene_delete_media_targets
from server.registry import deps
from server.modules.history_media_restore import (  # noqa: F401
    _restored_media, _media_references, _validate_staged_media, _restore_media_files, _remove_displaced_media,
)

_MAX_ENTRIES = 100
_STALE_SESSION_SECONDS = 7 * 24 * 60 * 60
_LOCK = threading.RLock()
_SESSION = ""
_ROOT: Path | None = None
_HISTORY: dict[str, list[dict[str, Any]]] = {"script": [], "characters": [], "pronunciation": []}
_CURSOR = {scope: 0 for scope in _HISTORY}
_RESTORING = False
_PENDING = PendingCaptures()


def _scope_for(path: str, method: str) -> str | None:
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if path.endswith("/overlap-mix") or path.endswith("/cue-mix"):
        # These endpoints only populate disposable derived-audio caches.
        return None
    if path.startswith("/api/pronunciation-dictionary"):
        return "pronunciation"
    if path.startswith("/api/characters") or path == "/api/project/apply-global-cast-updates":
        # Candidate preview/cleanup is deliberately temporary UI state.
        return None if "/candidates" in path else "characters"
    if (
        path == "/api/project"
        or path in {"/api/project/metadata", "/api/project/settings"}
        or path.startswith("/api/scenes/")
        or path.startswith("/api/lines/")
        or path == "/api/project/switch-characters"
    ):
        return "script"
    if path in {"/api/project/clear-takes", "/api/project/import-script", "/api/lines/cleanup-takes"}:
        return "script"
    return None


def _mutates_media(path: str, method: str) -> bool:
    return (
        any(
            fragment in path
            for fragment in ("/generate", "/regenerate", "/takes/", "/cue-mix", "/overlap-mix", "/clear-takes", "/cleanup-takes")
        )
        or path == "/api/lines/batch-delete"
        or (method == "DELETE" and path.startswith("/api/scenes/"))
    )


def _session_root() -> Path:
    global _SESSION, _ROOT
    if _ROOT is None:
        _SESSION = uuid4().hex
        _ROOT = deps.DATA_ROOT / "undo-sessions" / _SESSION
    # A development server or test process may have removed an older session
    # directory. Recreate this process's private blob store at every boundary.
    (_ROOT / "blobs").mkdir(parents=True, exist_ok=True)
    return _ROOT


def _stale_session_roots(base: Path, current: Path) -> list[Path]:
    cutoff = time.time() - _STALE_SESSION_SECONDS
    stale: list[Path] = []
    for item in base.iterdir():
        if not item.is_dir() or item == current:
            continue
        blobs = item / "blobs"
        last_modified = max(item.stat().st_mtime, blobs.stat().st_mtime if blobs.exists() else 0)
        if last_modified < cutoff:
            stale.append(item)
    return stale


def begin_history_session() -> None:
    """Start a clean in-memory session; old crash remnants are disposable."""
    global _SESSION, _ROOT, _HISTORY, _CURSOR
    with _LOCK:
        base = deps.DATA_ROOT / "undo-sessions"
        base.mkdir(parents=True, exist_ok=True)
        _SESSION = uuid4().hex
        _ROOT = base / _SESSION
        (_ROOT / "blobs").mkdir(parents=True, exist_ok=True)
        _HISTORY = {"script": [], "characters": [], "pronunciation": []}
        _CURSOR = {scope: 0 for scope in _HISTORY}
        _PENDING.reset()
        stale = _stale_session_roots(base, _ROOT)
    # Cleanup is deliberately detached from startup/project switching.
    threading.Thread(
        target=lambda: [shutil.rmtree(item, ignore_errors=True) for item in stale],
        name="irodori-undo-cleanup",
        daemon=True,
    ).start()


def end_history_session() -> None:
    """Discard this process's session-only Undo blobs on a graceful exit."""
    global _SESSION, _ROOT, _HISTORY, _CURSOR
    with _LOCK:
        root = _ROOT
        _SESSION = ""
        _ROOT = None
        _HISTORY = {"script": [], "characters": [], "pronunciation": []}
        _CURSOR = {scope: 0 for scope in _HISTORY}
        _PENDING.reset()
    if root is not None:
        shutil.rmtree(root, ignore_errors=True)


def _copy_blob(source: Path) -> str:
    hasher = hashlib.sha256()
    with source.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    target = _session_root() / "blobs" / digest
    if not target.exists():
        temporary = target.with_suffix(".tmp")
        temporary.parent.mkdir(parents=True, exist_ok=True)
        clonefile = getattr(os, "clonefile", None)
        if clonefile is not None:
            clonefile(source, temporary)
        else:
            with source.open("rb") as reader, temporary.open("wb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
        temporary.replace(target)
    return digest


def _files(root: Path, label: str) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        f"{label}/{source.relative_to(root).as_posix()}": _copy_blob(source)
        for source in root.rglob("*")
        if source.is_file()
    }


def _snapshot(scope: str, include_media: bool = False, media_targets: list[str] | None = None) -> dict[str, Any]:
    project_file = deps.PROJECT_FILE
    dictionary = deps.DATA_ROOT / "pronunciation-dictionary.json"
    global_file = deps.GLOBAL_CHARACTERS_FILE
    files: dict[str, str] = {}
    selected = [(project_file, "project.json")]
    if scope in {"pronunciation", "characters"}:
        selected.append((dictionary, "pronunciation-dictionary.json"))
    if scope == "characters":
        selected.append((global_file, "global-characters.json"))
    for file, label in selected:
        if file.is_file():
            files[label] = _copy_blob(file)
    if include_media:
        if media_targets is None:
            files.update(_files(deps.MEDIA_ROOT, "media"))
        else:
            for relative in media_targets:
                files.update(_files(deps.MEDIA_ROOT / relative, f"media/{relative}"))
    if scope == "characters":
        # Character mutations can only create, replace, or remove character
        # reference/avatar files. Takes and derived caches are not touched, so
        # scanning them here makes every cast edit scale with the whole project.
        files.update(_files(deps.MEDIA_ROOT / "characters", "media/characters"))
        files.update(_files(deps.GLOBAL_MEDIA_ROOT / "characters", "global-media/characters"))
    return {
        "scope": scope,
        "projectRoot": str(deps.ACTIVE_PROJECT_ROOT.resolve()),
        "files": files,
        "includeMedia": include_media,
        "mediaTargets": ["characters"] if scope == "characters" else media_targets,
    }


def _same(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if first["projectRoot"] != second["projectRoot"]:
        return False
    return _boundary_files(first) == _boundary_files(second) and (
        first["scope"] != "script"
        or _project_from_snapshot(first).get("revision") == _project_from_snapshot(second).get("revision")
    ) and _project_part(
        _project_from_snapshot(first), first["scope"]
    ) == _project_part(_project_from_snapshot(second), second["scope"])


def _project_part(value: dict[str, Any], scope: str) -> Any:
    if scope == "characters":
        return value.get("characters")
    if scope == "pronunciation":
        return value.get("pronunciationDictionary")
    return {key: item for key, item in value.items() if key not in {"revision", "characters"}}


def _project_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    digest = snapshot["files"].get("project.json")
    if digest is None:
        return {}
    return json.loads((_session_root() / "blobs" / digest).read_text(encoding="utf-8"))


def _boundary_files(snapshot: dict[str, Any]) -> dict[str, str]:
    return {key: value for key, value in snapshot["files"].items() if key != "project.json"}


def _live_metadata_matches(snapshot: dict[str, Any]) -> bool:
    destinations: dict[str, Path] = {}
    expected_project = _project_from_snapshot(snapshot)
    try:
        live_project = json.loads(deps.PROJECT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if _project_part(live_project, snapshot["scope"]) != _project_part(expected_project, snapshot["scope"]):
        return False
    if snapshot.get("scope") in {"pronunciation", "characters"}:
        destinations["pronunciation-dictionary.json"] = deps.DATA_ROOT / "pronunciation-dictionary.json"
    if snapshot.get("scope") == "characters":
        destinations["global-characters.json"] = deps.GLOBAL_CHARACTERS_FILE
    for name, destination in destinations.items():
        expected = snapshot["files"].get(name)
        if expected is None:
            if destination.exists():
                return False
            continue
        if not destination.is_file() or _copy_blob(destination) != expected:
            return False
    restored_media = _restored_media(snapshot)
    for name, destination in restored_media.items():
        expected_files = {path: digest for path, digest in snapshot["files"].items() if path.startswith(f"{name}/")}
        if snapshot.get("scope") == "characters":
            actual_files = _files(destination / "characters", f"{name}/characters")
        elif snapshot.get("mediaTargets") is not None:
            actual_files = {}
            for relative in snapshot["mediaTargets"]:
                actual_files.update(_files(destination / relative, f"{name}/{relative}"))
        else:
            actual_files = _files(destination, name)
        if actual_files != expected_files:
            return False
    return True



def capture_history_before(scope: str | None, include_media: bool = False, media_targets: list[str] | None = None) -> dict[str, Any] | None:
    if scope is None or _RESTORING:
        return None
    with _LOCK:
        snapshot = _snapshot(scope, include_media, media_targets)
        _PENDING.hold(snapshot)
        return snapshot


def release_history_capture(before: dict[str, Any] | None) -> None:
    """Stop protecting a captured snapshot's blobs once its request has finished."""
    if before is None:
        return
    with _LOCK:
        _PENDING.release(before)


def commit_history(scope: str | None, before: dict[str, Any] | None, auto_render_base_revision: int | None = None, generation_group_id: str | None = None) -> None:
    if scope is None or before is None or _RESTORING:
        return
    with _LOCK:
        after = _snapshot(scope, bool(before.get("includeMedia")), before.get("mediaTargets"))
        if _same(before, after):
            return
        if coalesce_generation_group(_HISTORY[scope], _CURSOR[scope], scope, before, after, generation_group_id):
            prune_unreferenced_blobs(_session_root() / "blobs", _HISTORY, _PENDING.blobs)
            return
        if coalesce_auto_render(_HISTORY[scope], _CURSOR[scope], scope, before, after, auto_render_base_revision, _session_root() / "blobs"):
            prune_unreferenced_blobs(_session_root() / "blobs", _HISTORY, _PENDING.blobs)
            return
        cursor = _CURSOR[scope]
        entries = _HISTORY[scope][:cursor]
        entries.append({"before": before, "after": after, "createdAt": time.time(), "generationGroupId": generation_group_id})
        _HISTORY[scope] = entries[-_MAX_ENTRIES:]
        _CURSOR[scope] = len(_HISTORY[scope])
        prune_unreferenced_blobs(_session_root() / "blobs", _HISTORY, _PENDING.blobs)


def _restore(snapshot: dict[str, Any], displaced_media: set[str] | None = None) -> None:
    if Path(snapshot["projectRoot"]).resolve() != deps.ACTIVE_PROJECT_ROOT.resolve():
        raise HTTPException(status_code=409, detail="プロジェクトを切り替えたため、この履歴は使えません。")
    root = _session_root()
    destinations: dict[str, Path] = {}
    if snapshot.get("scope") in {"pronunciation", "characters"}:
        destinations["pronunciation-dictionary.json"] = deps.DATA_ROOT / "pronunciation-dictionary.json"
    if snapshot.get("scope") == "characters":
        destinations["global-characters.json"] = deps.GLOBAL_CHARACTERS_FILE
    staging = root / f"restore-{uuid4().hex}"
    staging.mkdir()
    try:
        # Build the complete desired tree before replacing either live tree.
        for name, digest in snapshot["files"].items():
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / "blobs" / digest, target)
        restored_media = _restored_media(snapshot)
        _validate_staged_media(snapshot, staging)
        _restore_media_files(staging, restored_media)
        _remove_displaced_media(displaced_media or set(), restored_media)
        source_project = staging / "project.json"
        if source_project.is_file():
            desired = json.loads(source_project.read_text(encoding="utf-8"))
            current = json.loads(deps.PROJECT_FILE.read_text(encoding="utf-8"))
            scope = snapshot["scope"]
            if scope == "characters":
                current["characters"] = desired.get("characters", [])
            elif scope == "pronunciation":
                current["pronunciationDictionary"] = desired.get("pronunciationDictionary", [])
            else:
                for key in set(current) | set(desired):
                    if key not in {"revision", "characters"}:
                        if key in desired:
                            current[key] = desired[key]
                        else:
                            current.pop(key, None)
            if "revision" in current or "revision" in desired:
                current["revision"] = max(current.get("revision", 0), desired.get("revision", 0)) + 1
            source_project.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            destinations["project.json"] = deps.PROJECT_FILE
        for name, destination in destinations.items():
            source = staging / name
            if source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_suffix(destination.suffix + ".undo.tmp")
                shutil.copy2(source, temporary)
                temporary.replace(destination)
            else:
                destination.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def history_status(scope: str) -> dict[str, Any]:
    if scope not in _HISTORY:
        raise HTTPException(status_code=404, detail="Unknown history scope.")
    with _LOCK:
        return {
            "scope": scope,
            "canUndo": _CURSOR[scope] > 0,
            "canRedo": _CURSOR[scope] < len(_HISTORY[scope]),
            "busy": _RESTORING,
        }


def apply_history(scope: str, direction: str) -> dict[str, Any]:
    global _RESTORING
    if scope not in _HISTORY or direction not in {"undo", "redo"}:
        raise HTTPException(status_code=404, detail="Unknown history operation.")
    # Lock order: history _LOCK, DICTIONARY_LOCK, PROJECT_ROOT_LOCK, GLOBAL_CHARACTERS_LOCK.
    # The live check and file replacement must be one critical section so no
    # project, dictionary or cast writer can commit between them and be
    # silently undone. Every scope restores project.json, which carries the
    # project pronunciation entries, so the dictionary lock is always taken.
    with _LOCK, DICTIONARY_LOCK, deps.PROJECT_ROOT_LOCK, deps.GLOBAL_CHARACTERS_LOCK:
        cursor = _CURSOR[scope]
        if direction == "undo":
            if cursor == 0:
                return history_status(scope)
            entry = _HISTORY[scope][cursor - 1]
            next_cursor, snapshot = cursor - 1, entry["before"]
        else:
            if cursor >= len(_HISTORY[scope]):
                return history_status(scope)
            entry = _HISTORY[scope][cursor]
            next_cursor, snapshot = cursor + 1, entry["after"]
        live_boundary = entry["after"] if direction == "undo" else entry["before"]
        if not _live_metadata_matches(live_boundary):
            _HISTORY[scope] = []
            _CURSOR[scope] = 0
            raise HTTPException(
                status_code=409,
                detail="別の変更が保存されたため、この履歴は安全に適用できません。",
            )
        _RESTORING = True
        try:
            displaced_media = (
                {
                    path
                    for path in live_boundary["files"]
                    if path not in snapshot["files"] and path.startswith(("media/", "global-media/"))
                }
                if direction == "redo" or scope != "characters"
                else set()
            )
            _restore(snapshot, displaced_media)
            if snapshot.get("mediaTargets") is not None and deps.ACTIVE_PROJECT_PATH is not None:
                deps.sync_project_and_media_targets(
                    deps.ACTIVE_PROJECT_PATH,
                    deps.ACTIVE_PROJECT_ROOT,
                    snapshot["mediaTargets"],
                )
            elif _restored_media(snapshot):
                deps.persist_active_container()
            elif deps.ACTIVE_PROJECT_PATH is not None:
                deps.sync_project_entry(deps.ACTIVE_PROJECT_PATH, deps.ACTIVE_PROJECT_ROOT)
            # Restoring JSON bypasses write_project's derived-plan refresh.
            # The next playback must resolve gaps/takes from the restored state.
            deps.reset_overlap_preparation()
            _CURSOR[scope] = next_cursor
        finally:
            _RESTORING = False
        return history_status(scope)


@deps.app.middleware("http")
async def history_middleware(request, call_next):
    scope = _scope_for(request.url.path, request.method)
    path = request.url.path
    media_mutation = _mutates_media(path, request.method)
    media_targets = await _batch_delete_media_targets(request) if path in {"/api/lines/batch-delete", "/api/lines/cleanup-takes"} else None
    if media_mutation and media_targets is None:
        media_targets = _line_delete_media_targets(path, request.method)
    if media_mutation and media_targets is None:
        media_targets = await asyncio.to_thread(_scene_delete_media_targets, path, request.method)
    if media_mutation and media_targets is None:
        media_targets = _line_take_media_targets(path, request.method)
    if media_mutation and media_targets is None and path == "/api/project/clear-takes":
        media_targets = ["takes"]
    revision_header = request.headers.get("X-SCENA-History-Base-Revision") if media_mutation and path.endswith(("/generate", "/regenerate")) else None
    auto_render_base_revision = int(revision_header) if revision_header and revision_header.isdecimal() else None
    group_header = request.headers.get("X-SCENA-History-Group") if path.endswith(("/generate", "/regenerate")) else None
    try:
        generation_group_id = str(UUID(group_header)) if group_header else None
    except ValueError:
        generation_group_id = None
    before = await asyncio.to_thread(capture_history_before, scope, media_mutation, media_targets)
    try:
        response = await call_next(request)
        if response.status_code < 400:
            await asyncio.to_thread(commit_history, scope, before, auto_render_base_revision, generation_group_id)
            if scope is not None:
                response.headers["X-SCENA-History-Scope"] = scope
        return response
    finally:
        # A cancelled request (client disconnect) must still release its capture.
        with anyio.CancelScope(shield=True):
            await asyncio.to_thread(release_history_capture, before)


@deps.app.on_event("startup")
def start_history_session() -> None:
    begin_history_session()


@deps.app.on_event("shutdown")
def stop_history_session() -> None:
    end_history_session()


@deps.app.get("/api/history/{scope}")
def get_history(scope: str) -> dict[str, Any]:
    return history_status(scope)


@deps.app.post("/api/history/{scope}/{direction}")
def change_history(scope: str, direction: str) -> dict[str, Any]:
    return apply_history(scope, direction)


deps.register(
    __name__,
    [
        "apply_history",
        "begin_history_session",
        "capture_history_before",
        "commit_history",
        "end_history_session",
        "history_status",
        "release_history_capture",
    ],
)

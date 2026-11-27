from __future__ import annotations

import os
import tempfile
import threading
from functools import wraps

from server.app_deps import json, shutil, Path, Any, urlsplit, HTTPException
from server.registry import deps
from pydantic import ValidationError
from server.modules.cast_identity import character_identity, matches_global_candidates
from server.modules.project_portability import (
    materialize_cast_global_characters,
    project_backup_media,  # noqa: F401 - public compatibility re-export
    project_backup_snapshot,  # noqa: F401 - public compatibility re-export
)


def canonical_project_media_url(value: str) -> str:
    """Convert a desktop API media URL back to its portable project form."""
    parsed = urlsplit(value)
    if (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and (parsed.path.startswith("/media/") or parsed.path.startswith("/global-media/"))
    ):
        return parsed.path
    return value


def normalize_project_media_urls(value: Any) -> Any:
    """Keep UI-resolved localhost URLs out of portable project persistence."""
    if isinstance(value, list):
        return [normalize_project_media_urls(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: canonical_project_media_url(item)
        if key.endswith("Url") and isinstance(item, str)
        else normalize_project_media_urls(item)
        for key, item in value.items()
    }


def normalize_line_pronunciations(line: dict[str, Any]) -> None:
    text, raw = line.get("text"), line.get("pronunciations")
    if not isinstance(text, str) or raw is None:
        return
    accepted: list[dict[str, Any]] = []
    for item in (
        sorted(
            (item for item in raw if isinstance(item, dict)),
            key=lambda item: (item.get("start", -1), item.get("end", -1)),
        )
        if isinstance(raw, list)
        else []
    ):
        start, end = item.get("start"), item.get("end")
        source, reading, item_id = item.get("text"), item.get("reading"), item.get("id")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not isinstance(source, str)
            or not isinstance(reading, str)
            or not isinstance(item_id, str)
        ):
            continue
        if (
            not item_id
            or start < 0
            or end <= start
            or end > len(text)
            or not reading
            or "\n" in reading
            or text[start:end] != source
        ):
            continue
        if any(start < other["end"] and other["start"] < end for other in accepted):
            continue
        accepted.append({"id": item_id, "start": start, "end": end, "text": source, "reading": reading})
    line["pronunciations"] = accepted


def read_global_characters() -> list[dict[str, Any]]:
    deps.ensure_data_root()
    try:
        loaded = json.loads(deps.GLOBAL_CHARACTERS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Global character library is invalid JSON: {error}") from error
    if not isinstance(loaded, list):
        raise HTTPException(status_code=500, detail="Global character library is invalid.")
    characters = [deps.normalize_character_profile(item) for item in loaded if isinstance(item, dict)]
    global_root = deps.GLOBAL_MEDIA_ROOT.resolve()
    for character in characters:
        media_url = str(character.get("referenceAudioUrl", ""))
        if not media_url.startswith("/global-media/"):
            continue
        reference = (global_root / media_url[len("/global-media/") :]).resolve()
        try:
            reference.relative_to(global_root)
        except ValueError:
            continue
        character["referenceFile"] = str(reference)
    return characters


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        # Windows does not permit opening a directory with os.open. The file
        # itself is already flushed above; directory fsync is a Unix durability
        # step and has no portable Windows equivalent in Python's os module.
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


# Guards global cast library read-modify-write. Acquire it only after
# PROJECT_ROOT_LOCK (see docs/architecture.md, project mutation locking).
GLOBAL_CHARACTERS_LOCK = threading.RLock()


def cast_mutation(function):
    """Hold the project lock, then the global cast lock, across one read-modify-write."""
    @wraps(function)
    def locked(*args, **kwargs):
        with deps.PROJECT_ROOT_LOCK, GLOBAL_CHARACTERS_LOCK:
            return function(*args, **kwargs)
    return locked


def write_global_characters(characters: list[dict[str, Any]]) -> None:
    deps.GLOBAL_CHARACTERS_ROOT.mkdir(parents=True, exist_ok=True)
    normalized = [deps.normalize_character_profile(item) for item in characters if isinstance(item, dict)]
    with GLOBAL_CHARACTERS_LOCK:
        atomic_write(deps.GLOBAL_CHARACTERS_FILE, (json.dumps(normalized, ensure_ascii=False, indent=2) + "\n").encode())


def hydrate_project_media(project: dict[str, Any]) -> dict[str, Any]:
    """Rebuild absolute local paths after a workspace has been moved."""
    project = normalize_project_media_urls(project)
    for character in project.get("characters", []):
        if isinstance(character, dict) and str(character.get("referenceAudioUrl", "")).startswith("/media/"):
            character["referenceFile"] = str(deps.MEDIA_ROOT / str(character["referenceAudioUrl"])[7:])
            character.setdefault("scope", "project")
    for candidate in project.get("candidates", []):
        if isinstance(candidate, dict) and str(candidate.get("audioUrl", "")).startswith("/media/"):
            candidate["file"] = str(deps.MEDIA_ROOT / str(candidate["audioUrl"])[7:])
    return project


def project_character_matches_global(character: dict[str, Any]) -> bool:
    """Whether an archived project cast still equals its global-library source."""
    if not str(character.get("id", "")):
        return False
    return matches_global_candidates(character, read_global_characters())


def resolved_project_characters(project: dict[str, Any]) -> dict[str, Any]:
    local_characters = [
        dict(character)
        for character in project.get("characters", [])
        if isinstance(character, dict) and character.get("scope") != "global"
    ]
    local_ids: set[str] = set()
    local_hashes: set[str] = set()
    for character in local_characters:
        character.setdefault("scope", "project")
        character_id, audio_hash = character_identity(character)
        if character_id:
            local_ids.add(character_id)
        if audio_hash:
            local_hashes.add(audio_hash)
    merged = local_characters[:]
    for global_character in read_global_characters():
        character = dict(global_character)
        character["scope"] = "global"
        character_id, audio_hash = character_identity(character)
        if character_id in local_ids or (audio_hash and audio_hash in local_hashes):
            continue
        merged.append(character)
    project["characters"] = merged
    return project


def repair_draft_cast_context_placeholders(project: dict[str, Any]) -> None:
    """Replace the exact placeholder emitted by the cast-context regression."""
    contexts = project.get("scriptCastContexts")
    if not isinstance(contexts, dict):
        return
    characters = {
        str(character.get("id", "")): character
        for character in project.get("characters", [])
        if isinstance(character, dict)
    }
    for character_id, context in contexts.items():
        if not isinstance(context, dict):
            continue
        if context.get("role") != "登場人物" or context.get("description") != "この台本の登場人物。":
            continue
        character = characters.get(str(character_id))
        if not character:
            continue
        details = deps.normalize_character_profile_details(character.get("profileDetails"))
        context["role"] = str(details.get("role", "")).strip() or "登場人物"
        context["description"] = deps.draft_reader_introduction(character)


def read_project() -> dict[str, Any]:
    deps.ensure_data_root()
    try:
        project = json.loads(deps.PROJECT_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=500, detail=f"Project file is invalid JSON: {error}") from error
    if not isinstance(project, dict):
        raise HTTPException(status_code=500, detail="Project file has an invalid root value.")
    # TTS selection is device-local. Ignore legacy project-persisted values and
    # expose only the registry-derived value to existing UI/runtime consumers.
    project.pop("ttsSelection", None)
    if "effective_tts_selection" in deps.names():
        selection = deps.effective_tts_selection()
        if selection is not None:
            project["ttsSelection"] = selection
    revision = project.get("revision", 0)
    project["revision"] = revision if isinstance(revision, int) and revision >= 0 else 0
    try:
        deps.StudioProjectModel.model_validate(project)
    except ValidationError as error:
        raise HTTPException(
            status_code=500, detail=f"Project file does not match the persisted schema: {error}"
        ) from error
    deps.normalize_project_cues(project)
    project = resolved_project_characters(hydrate_project_media(project))
    project["characters"] = [
        deps.normalize_character_profile(character)
        for character in project.get("characters", [])
        if isinstance(character, dict)
    ]
    repair_draft_cast_context_placeholders(project)
    return project


def write_project(
    project: dict[str, Any],
    *,
    expected_revision: int | None = None,
    project_only: bool = False,
) -> dict[str, Any]:
    with deps.PROJECT_ROOT_LOCK:
        return _write_project_locked(
            project,
            expected_revision=expected_revision,
            project_only=project_only,
        )


def _reconcile_script_dictionary_after_change(project: dict[str, Any], persisted: dict[str, Any] | None) -> None:
    if persisted is None:
        return
    if deps.script_pronunciation_signature(project) != deps.script_pronunciation_signature(persisted):
        deps.reconcile_script_pronunciations(project)


def _persisted_project_revision() -> tuple[int, dict[str, Any] | None]:
    if not deps.PROJECT_FILE.exists():
        return -1, None
    try:
        persisted = json.loads(deps.PROJECT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0, None
    value = persisted.get("revision", 0) if isinstance(persisted, dict) else 0
    return (value if isinstance(value, int) and value >= 0 else 0), persisted


def _write_project_locked(
    project: dict[str, Any],
    *,
    expected_revision: int | None = None,
    project_only: bool = False,
) -> dict[str, Any]:
    source_project = project
    project = normalize_project_media_urls(json.loads(json.dumps(project, ensure_ascii=False)))
    project.pop("ttsSelection", None)
    current_revision, persisted = _persisted_project_revision()
    if expected_revision is not None and expected_revision != current_revision:
        current_project = read_project()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "project_revision_conflict",
                "message": "別の変更が先に保存されました。",
                "currentRevision": current_revision,
                "currentProject": current_project,
            },
        )
    project["revision"] = current_revision + 1
    try:
        deps.StudioProjectModel.model_validate(project)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=f"Project does not match the persisted schema: {error}") from error
    # On first boot there is no project file yet; resolving globals there would
    # re-enter ensure_data_root through read_global_characters.
    if deps.PROJECT_FILE.exists():
        project = resolved_project_characters(project)
    project["pronunciationDictionary"] = deps.project_pronunciation_snapshot(project)
    _reconcile_script_dictionary_after_change(project, persisted)
    project["characters"] = [
        deps.normalize_character_profile(character)
        for character in project.get("characters", [])
        if isinstance(character, dict) and character.get("scope") != "global"
    ]
    for character in project["characters"]:
        character.pop("scope", None)
    for scene in project.get("scenes", []):
        if isinstance(scene, dict):
            deps.normalize_scene_cues(scene)
            scene.pop("description", None)
            for line in scene.get("lines", []):
                if isinstance(line, dict):
                    normalize_line_pronunciations(line)
    deps.ACTIVE_PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
    previous_bytes = deps.PROJECT_FILE.read_bytes() if deps.PROJECT_FILE.exists() else None
    atomic_write(deps.PROJECT_FILE, (json.dumps(project, ensure_ascii=False, indent=2) + "\n").encode())
    try:
        if deps.ACTIVE_PROJECT_PATH is not None:
            if project_only:
                deps.sync_project_entry(deps.ACTIVE_PROJECT_PATH, deps.ACTIVE_PROJECT_ROOT)
            else:
                deps.sync_container(
                    deps.ACTIVE_PROJECT_PATH,
                    deps.ACTIVE_PROJECT_ROOT,
                    include_derived_audio=False,
                )
    except Exception:
        if previous_bytes is None:
            deps.PROJECT_FILE.unlink(missing_ok=True)
        else:
            atomic_write(deps.PROJECT_FILE, previous_bytes)
        raise
    # Callers commonly return the object they passed to this function.
    source_project["revision"] = project["revision"]
    source_project["pronunciationDictionary"] = json.loads(
        json.dumps(project["pronunciationDictionary"], ensure_ascii=False)
    )
    saved = read_project()
    if "refresh_overlap_preparation" in deps.names():
        deps.refresh_overlap_preparation(saved)
    return saved


def move_scratch_project_to(destination: Path) -> dict[str, Any]:
    """Publish the scratch workspace as one .scena file, then activate its cache."""
    if deps.ACTIVE_PROJECT_PATH is not None:
        with deps.PROJECT_ROOT_LOCK:
            project = materialize_cast_global_characters(read_project())
            write_project(project)
        return {"project": read_project(), "workspace": deps.workspace_info(), "moved": False}
    destination = destination.expanduser()
    if not destination.is_absolute() or destination.suffix.lower() != ".scena":
        raise HTTPException(status_code=422, detail="保存先には.scenaファイルを指定してください。")
    deps.require_external_project_destination(destination.parent)
    with deps.PROJECT_ROOT_LOCK:
        project = materialize_cast_global_characters(read_project())
        write_project(project)
    if destination.exists():
        raise HTTPException(status_code=409, detail="同名のプロジェクトファイルがすでにあります。")
    prepared_root = deps.working_root(destination).with_name(f"{deps.working_root(destination).name}-first-save-{os.getpid()}")
    try:
        # The scratch project shares DATA_ROOT with application-wide registries,
        # runtimes, models, and settings. Only the project document and its media
        # belong in the first saved container.
        deps.sync_container(
            destination,
            deps.ACTIVE_PROJECT_ROOT,
            root_entries=frozenset({"project.json", "media"}),
        )
        signature = deps.container_signature(destination)
        deps.prepare_saved_workspace(destination, deps.ACTIVE_PROJECT_ROOT, prepared_root)
        deps.activate_project_container(destination, prepared_root=prepared_root, expected_signature=signature)
    except Exception as error:
        shutil.rmtree(prepared_root, ignore_errors=True)
        destination.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise HTTPException(status_code=500, detail=f"プロジェクトファイルへ保存できませんでした: {error}") from error
        raise
    return {"project": read_project(), "workspace": deps.workspace_info(), "moved": True}


@cast_mutation
def migrate_legacy_scratch_characters() -> None:
    """Promote existing pre-library scratch voices to the global library once."""
    if deps.ACTIVE_PROJECT_ROOT.resolve() != deps.default_workspace_root() or not deps.PROJECT_FILE.is_file():
        return
    project = read_project()
    legacy = [
        character
        for character in project.get("characters", [])
        if isinstance(character, dict) and character.get("scope") != "global"
    ]
    if not legacy:
        return
    global_characters = read_global_characters()
    existing_ids = {str(character.get("id", "")) for character in global_characters}
    promoted = False
    for character in legacy:
        character_id = str(character.get("id", ""))
        source = Path(str(character.get("referenceFile", ""))).resolve()
        if not character_id or not source.is_file() or character_id in existing_ids:
            continue
        target = deps.GLOBAL_MEDIA_ROOT / "characters" / deps.safe_segment(character_id) / "reference.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        global_character = dict(character)
        global_character.update(
            {
                "scope": "global",
                "referenceAudioUrl": deps.global_media_url(target),
                "referenceFile": str(target),
                "audioHash": deps.audio_digest(target),
            }
        )
        global_characters.append(global_character)
        existing_ids.add(character_id)
        promoted = True
    if promoted:
        write_global_characters(global_characters)
        project["characters"] = [
            character for character in project.get("characters", []) if character.get("scope") == "global"
        ]
        write_project(project)


deps.register(
    __name__,
    [
        "GLOBAL_CHARACTERS_LOCK",
        "atomic_write",
        "canonical_project_media_url",
        "cast_mutation",
        "hydrate_project_media",
        "materialize_cast_global_characters",
        "migrate_legacy_scratch_characters",
        "move_scratch_project_to",
        "project_backup_media",
        "project_backup_snapshot",
        "project_character_matches_global",
        "normalize_project_media_urls",
        "repair_draft_cast_context_placeholders",
        "read_global_characters",
        "read_project",
        "resolved_project_characters",
        "write_global_characters",
        "write_project",
    ],
)

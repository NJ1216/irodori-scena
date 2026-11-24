from __future__ import annotations

from server.app_deps import json, math, re, shutil, subprocess, sys, Path, Any, HTTPException
from server.registry import deps
from server.modules.connection_settings import delete_connection_api_key, read_connection_settings, write_engine_directory  # noqa: F401


def default_project() -> dict[str, Any]:
    return {
        "version": 1,
        "revision": 0,
        "id": deps.new_id("project"),
        "title": "",
        "characters": [],
        "candidates": [],
        "scenes": [{"id": deps.new_id("scene"), "title": "Scene A", "lines": [{
            "id": deps.new_id("line"),
            "characterId": "",
            "text": "",
            "stageDirection": "",
            "takes": [],
            "selectedTakeId": None,
        }]}],
        "settings": {
            "speechRate": 1.2,
            "steps": 16,
            "textCfg": 3.0,
            "voiceCfg": 5.0,
            "captionCfg": 3.0,
            "seed": 0,
            "quality": "fast",
            "lineGap": 0.7,
            "llmBaseUrl": "http://127.0.0.1:11434/v1",
            "llmModel": "",
        },
    }


def default_workspace_root() -> Path:
    return deps.DATA_ROOT.resolve()


def workspace_root_label(root: Path) -> str:
    return "scena-data（未保存）" if root.resolve() == default_workspace_root() else root.name


def workspace_info() -> dict[str, Any]:
    root = deps.ACTIVE_PROJECT_ROOT.resolve()
    project_path = deps.ACTIVE_PROJECT_PATH
    return {
        "path": str(project_path.resolve() if project_path else root),
        "name": project_path.name if project_path else workspace_root_label(root),
        "isScratch": project_path is None,
    }


def save_active_workspace_state() -> None:
    deps.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    deps.APP_STATE_FILE.write_text(
        json.dumps({"activeProjectPath": str(deps.ACTIVE_PROJECT_PATH.resolve()) if deps.ACTIVE_PROJECT_PATH else ""}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def activate_project_root(root: Path, *, persist: bool = True) -> None:
    """Switch the single local workspace used by the API process."""
    resolved = root.expanduser().resolve()
    deps.release_container_lock()
    with deps.PROJECT_ROOT_LOCK:
        deps.ACTIVE_PROJECT_ROOT = resolved
        deps.ACTIVE_PROJECT_PATH = None
        deps.PROJECT_FILE = resolved / "project.json"
        deps.MEDIA_ROOT = resolved / "media"
        if persist:
            save_active_workspace_state()


def restore_active_workspace() -> None:
    from server.modules.workspace_restore import restore_active_workspace as restore

    restore()


def activate_project_container(path: Path, *, persist: bool = True, prepared_root: Path | None = None, expected_signature: tuple[int, int, int] | None = None) -> None:
    resolved = path.expanduser().resolve()
    previous = deps.active_container_path()
    old_state = (deps.ACTIVE_PROJECT_PATH, deps.ACTIVE_PROJECT_ROOT, deps.PROJECT_FILE, deps.MEDIA_ROOT)
    deps.acquire_container_lock(resolved)
    root = deps.working_root(resolved)
    previous_root = root.with_name(f".{root.name}.previous")
    try:
        if expected_signature is not None and deps.container_signature(resolved) != expected_signature:
            raise HTTPException(status_code=409, detail="確認中に.scenaプロジェクトが変更されました。もう一度開いてください。")
        if prepared_root is None:
            deps.extract_container(resolved, root)
        else:
            root.parent.mkdir(parents=True, exist_ok=True)
            if previous_root.exists():
                shutil.rmtree(previous_root)
            if root.exists():
                root.replace(previous_root)
            prepared_root.replace(root)
        with deps.PROJECT_ROOT_LOCK:
            deps.ACTIVE_PROJECT_PATH = resolved
            deps.ACTIVE_PROJECT_ROOT = root
            deps.PROJECT_FILE = root / "project.json"
            deps.MEDIA_ROOT = root / "media"
            if persist:
                save_active_workspace_state()
        if prepared_root is not None and previous_root.exists():
            shutil.rmtree(previous_root)
    except Exception:
        with deps.PROJECT_ROOT_LOCK:
            deps.ACTIVE_PROJECT_PATH, deps.ACTIVE_PROJECT_ROOT, deps.PROJECT_FILE, deps.MEDIA_ROOT = old_state
        if prepared_root is not None and root.exists():
            shutil.rmtree(root)
        if prepared_root is not None and previous_root.exists():
            previous_root.replace(root)
        deps.release_container_lock()
        if previous is not None:
            deps.acquire_container_lock(previous)
        raise


def discard_restored_voice_candidates() -> None:
    """Remove audition-only VoiceDesign state when a new API process starts."""
    project = deps.read_project()
    if not project.get("candidates"):
        return
    deps.clear_voice_candidates(project)
    deps.write_project(project)


def choose_directory(prompt: str) -> Path:
    """Open a native folder picker on the local macOS host."""
    if sys.platform != "darwin":
        raise HTTPException(status_code=501, detail="プロジェクトフォルダの選択は現在macOSでのみ利用できます。")
    script = f"POSIX path of (choose folder with prompt {json.dumps(prompt, ensure_ascii=False)})"
    try:
        completed = subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True, timeout=120)
    except subprocess.CalledProcessError as error:
        raise HTTPException(status_code=499, detail="フォルダの選択をキャンセルしました。") from error
    except subprocess.TimeoutExpired as error:
        raise HTTPException(status_code=504, detail="フォルダの選択がタイムアウトしました。") from error
    path = Path(completed.stdout.strip()).expanduser()
    if not path.is_dir():
        raise HTTPException(status_code=422, detail="選択されたフォルダを開けませんでした。")
    return path.resolve()


def is_within_directory(path: Path, directory: Path) -> bool:
    """Return whether path is the directory itself or one of its descendants."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def require_external_project_destination(destination_parent: Path) -> None:
    if is_within_directory(destination_parent, deps.DATA_ROOT):
        raise HTTPException(
            status_code=422,
            detail="scena-data とその配下は内部作業用フォルダのため、プロジェクトの保存先には選べません。別のフォルダを選択してください。",
        )


def project_folder_name(title: str) -> str:
    clean = re.sub("[\\\\/:\\x00-\\x1f]", "_", title).strip(". ")
    return f"{clean or 'irodori-scena'}.scena"


def discard_legacy_llm_settings() -> None:
    try:
        loaded = json.loads(deps.CONNECTION_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if not isinstance(loaded, dict) or not any(key in loaded for key in ("provider", "baseUrl", "model", "apiKeyEnabled")):
        return
    delete_connection_api_key(loaded)
    write_engine_directory(str(loaded.get("engineDir", "")))


def ensure_data_root() -> None:
    deps.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    discard_legacy_llm_settings()
    deps.GLOBAL_CHARACTERS_ROOT.mkdir(parents=True, exist_ok=True)
    deps.GLOBAL_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    if not deps.GLOBAL_CHARACTERS_FILE.exists():
        deps.GLOBAL_CHARACTERS_FILE.write_text("[]\n", encoding="utf-8")
    deps.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    if not deps.PROJECT_FILE.exists():
        deps.write_project(default_project())


def draft_debug_directory(job_id: str) -> Path:
    """Return the raw-response path, creating it only in development."""
    directory = deps.LLM_DEBUG_ROOT / deps.safe_segment(job_id)
    if deps.LLM_DEBUG_ENABLED:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_draft_debug_response(path: Path, content: object) -> None:
    """Persist raw model output before any JSON recovery or scene filtering."""
    if not deps.LLM_DEBUG_ENABLED:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(str(content), encoding="utf-8")
    temporary.replace(path)


def write_draft_debug_request(
    response_path: Path,
    *,
    request: deps.DraftRequest,
    system: str,
    user: dict[str, Any],
    max_tokens: int,
    sampling: dict[str, Any],
) -> None:
    """Persist the exact prompt without endpoint credentials or API secrets."""
    request_path = response_path.with_name(f"{response_path.stem}-request.json")
    write_draft_debug_response(
        request_path,
        json.dumps(
            {
                "provider": request.provider,
                "model": request.model,
                "sampling": sampling,
                "max_tokens": max_tokens,
                "callBudget": (deps.active_draft_capability_profile() or {}).get("lastCall", {}),
                "system": system,
                "user": user,
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def draft_yield_profile_key(request: deps.DraftRequest) -> str:
    profile = deps.active_draft_capability_profile() or {}
    backend = str(profile.get("runtimeBackend") or profile.get("backend") or request.provider)
    context = profile.get("runtimeContextLimit") or profile.get("effectiveContext") or "unknown"
    structured = "structured" if deps.ollama_structured_enabled(request) else "plain"
    fingerprint = str(profile.get("modelFingerprint") or request.model)
    return f"draft-performance-v4:{fingerprint}:{backend}:{context}:{structured}"


def draft_performance_profile(request: deps.DraftRequest) -> dict[str, Any]:
    """Return conservative accepted characters and healthy batch after three responses."""
    with deps.DRAFT_YIELD_PROFILES_LOCK:
        try:
            payload = json.loads(deps.LLM_YIELD_PROFILES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"samples": 0, "acceptedCharacters": 600, "batch": 1}
    record = payload.get(draft_yield_profile_key(request), {}) if isinstance(payload, dict) else {}
    history = record.get("history", []) if isinstance(record, dict) and record.get("schemaVersion") == 4 else []
    valid = [item for item in history[-20:] if isinstance(item, dict)]
    if len(valid) < 3:
        return {"samples": len(valid), "acceptedCharacters": 600, "batch": 1}
    accepted = sorted(max(0, int(item.get("acceptedCharacters", 0))) for item in valid)
    position = max(0, math.ceil(len(accepted) * .20) - 1)
    healthy = [max(1, int(item.get("completedDevelopments", 0))) for item in valid
               if not any(item.get(flag) for flag in ("truncated", "repeated", "transportFailed"))
               and int(item.get("completedDevelopments", 0)) == int(item.get("requestedDevelopments", 0))]
    batch = sorted(healthy)[max(0, math.ceil(len(healthy) * .20) - 1)] if len(healthy) >= 3 else 1
    return {"samples": len(valid), "acceptedCharacters": max(400, min(900, accepted[position])),
            "batch": max(1, min(3, batch))}


def draft_yield_ratio(request: deps.DraftRequest) -> tuple[float, int]:
    """Return the recent validated-yield 20th percentile after three samples."""
    with deps.DRAFT_YIELD_PROFILES_LOCK:
        try:
            payload = json.loads(deps.LLM_YIELD_PROFILES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return (deps.DRAFT_DEFAULT_YIELD_RATIO, 0)
        record = payload.get(draft_yield_profile_key(request), {}) if isinstance(payload, dict) else {}
        if not isinstance(record, dict) or record.get("schemaVersion") != 4:
            return (deps.DRAFT_DEFAULT_YIELD_RATIO, 0)
        history = record.get("history", [])
        valid = [float(item.get("acceptedCharacters", 0)) / max(1, float(item.get("requestedCharacters", 1)))
                 for item in history[-20:] if isinstance(item, dict)]
        if len(valid) < 3:
            return (deps.DRAFT_DEFAULT_YIELD_RATIO, len(valid))
        ordered = sorted(valid)
        ratio = ordered[max(0, math.ceil(len(ordered) * 0.20) - 1)]
        return (max(0.25, min(deps.DRAFT_MAX_YIELD_RATIO, ratio)), len(valid))


def record_draft_yield(request: deps.DraftRequest, *, requested: int, accepted: int,
                       requested_developments: int = 1, completed_developments: int = 0,
                       batch_size: int = 1, truncated: bool = False, repeated: bool = False,
                       transport_failed: bool = False, section: str = "body") -> float:
    """Persist the latest twenty successful validated-character yields."""
    observed = accepted / max(1, requested)
    observed = max(deps.DRAFT_MIN_YIELD_RATIO, min(deps.DRAFT_MAX_YIELD_RATIO, observed))
    with deps.DRAFT_YIELD_PROFILES_LOCK:
        try:
            payload = json.loads(deps.LLM_YIELD_PROFILES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        key = draft_yield_profile_key(request)
        previous = payload.get(key, {}) if isinstance(payload.get(key), dict) else {}
        if previous.get("schemaVersion") != 4:
            previous = {}
        history = [item for item in previous.get("history", []) if isinstance(item, dict)]
        history = [*history[-19:], {
            "requestedCharacters": int(requested), "acceptedCharacters": int(accepted),
            "requestedDevelopments": int(requested_developments),
            "completedDevelopments": int(completed_developments), "batchSize": int(batch_size),
            "truncated": bool(truncated), "repeated": bool(repeated),
            "transportFailed": bool(transport_failed), "section": section,
        }]
        payload[key] = {
            "schemaVersion": 4, "history": history, "samples": len(history), "updatedAt": deps.now_ms(),
        }
        deps.LLM_YIELD_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = deps.LLM_YIELD_PROFILES_FILE.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(deps.LLM_YIELD_PROFILES_FILE)
    return draft_yield_ratio(request)[0]


deps.register(
    __name__,
    [
        "activate_project_root",
        "activate_project_container",
        "choose_directory",
        "default_project",
        "default_workspace_root",
        "discard_legacy_llm_settings",
        "draft_debug_directory",
        "draft_yield_profile_key",
        "draft_performance_profile",
        "draft_yield_ratio",
        "ensure_data_root",
        "is_within_directory",
        "project_folder_name",
        "record_draft_yield",
        "require_external_project_destination",
        "restore_active_workspace",
        "discard_restored_voice_candidates",
        "save_active_workspace_state",
        "workspace_info",
        "workspace_root_label",
        "write_draft_debug_request",
        "write_draft_debug_response",
    ],
)

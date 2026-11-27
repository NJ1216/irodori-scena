from __future__ import annotations

from typing import Any
from copy import deepcopy

from server.app_deps import HTTPException
from server.registry import deps
from server.modules.pronunciation_dictionary import dictionary_transaction


@deps.app.post("/api/pronunciation-dictionary/change")
@dictionary_transaction
def change_pronunciation_dictionary(request: deps.PronunciationChangeRequest) -> dict[str, Any]:
    if request.operation in {"suggest-manual", "suggest-cast"}:
        # LLM suggestions never hold the project lock; they do not rewrite project.json.
        return _change_pronunciation_dictionary(request)
    with deps.PROJECT_ROOT_LOCK:
        return _change_pronunciation_dictionary(request)


def _change_pronunciation_dictionary(request: deps.PronunciationChangeRequest) -> dict[str, Any]:
    project = deps.read_project()
    before = deps.combined_pronunciation_entries(project)
    operation = request.operation
    if operation == "add-manual":
        _add_manual_to_scopes(project, request)
    elif operation == "update-manual":
        global_id = request.global_id or (request.entry_id if request.scope == "global" else "")
        project_id = request.project_id or (request.entry_id if request.scope == "project" else "")
        if project_id:
            _ensure_unique_project_manual_term(project, request.term, project_id)
        if global_id:
            deps.update_manual_pronunciation_entry(global_id, request.term, request.reading)
            if request.locked is not None:
                deps.set_pronunciation_lock(global_id, request.locked)
        if project_id:
            _update_project_entry(project, project_id, request.term, request.reading, request.locked)
            deps.write_project(project)
    elif operation == "delete-manual":
        deps.delete_manual_pronunciation_entry(request.entry_id)
    elif operation == "add-cast":
        deps.add_cast_pronunciation_entry(request.character_id, request.term, request.reading)
    elif operation == "update-cast":
        deps.update_cast_pronunciation_reading(request.entry_id, request.reading)
    elif operation == "delete-cast":
        deps.delete_manual_cast_pronunciation_entry(request.entry_id)
    elif operation == "suggest-manual":
        deps.track_default_llm_usage("発音提案", deps.suggest_manual_pronunciation_readings)
    elif operation == "suggest-cast":
        deps.track_default_llm_usage("キャスト発音提案", deps.suggest_cast_pronunciation_readings)
    elif operation == "toggle-scope":
        _toggle_scope(project, request)
    refreshed_project = deps.read_project()
    after = deps.combined_pronunciation_entries(refreshed_project)
    return {"entries": deps.scoped_pronunciation_rows(refreshed_project),
            "affectedLineIds": deps.affected_pronunciation_line_ids(before, after)}


def _add_manual_to_scopes(project: dict[str, Any], request: deps.PronunciationChangeRequest) -> None:
    selected = list(dict.fromkeys(request.scopes if request.scopes is not None else [request.scope]))
    if not selected:
        raise HTTPException(status_code=422, detail="保存先を1つ以上選択してください。")
    term = request.term.strip()
    if not term:
        raise HTTPException(status_code=422, detail="語句を入力してください。")
    reading = deps.validate_reading(request.reading)
    global_entries = deps.read_pronunciation_dictionary()
    if "global" in selected:
        deps.ensure_unique_manual_term(global_entries, term)
    if "project" in selected:
        _ensure_unique_project_manual_term(project, term, "")

    base = {"term": term, "reading": reading, "source": "manual", "characterId": None,
            "sourceKeys": ["manual"], "suggestedReading": reading, "userEdited": True}
    next_global = deepcopy(global_entries)
    next_project = deepcopy(project)
    if "global" in selected:
        next_global.append({**base, "id": deps.new_id("pronunciation")})
    if "project" in selected:
        next_project.setdefault("pronunciationDictionary", []).append({
            **base, "id": deps.new_id("pronunciation"), "projectScopeOrigin": "manual",
        })

    # Validate both destinations before persistence, then restore the exact
    # preimages if the second atomic file replacement fails.
    original_project = deps.PROJECT_FILE.read_bytes() if deps.PROJECT_FILE.exists() else None
    original_global = deps.dictionary_file().read_bytes() if deps.dictionary_file().exists() else None
    try:
        if "project" in selected:
            deps.write_project(next_project)
        if "global" in selected:
            deps.write_pronunciation_dictionary(next_global)
    except Exception:
        _restore_file(deps.PROJECT_FILE, original_project)
        _restore_file(deps.dictionary_file(), original_global)
        if deps.ACTIVE_PROJECT_PATH is not None and original_project is not None:
            deps.sync_container(deps.ACTIVE_PROJECT_PATH, deps.ACTIVE_PROJECT_ROOT)
        raise


def _restore_file(path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".transaction-rollback")
    temporary.write_bytes(content)
    temporary.replace(path)


def _update_project_entry(project: dict[str, Any], entry_id: str, term: str, reading: str, locked: bool | None) -> None:
    entry = next((item for item in project.get("pronunciationDictionary", []) if item.get("id") == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="PROJECTの辞書項目が見つかりません。")
    term = term.strip()
    if not term:
        raise HTTPException(status_code=422, detail="語句を入力してください。")
    _ensure_unique_project_manual_term(project, term, entry_id)
    entry.update({
        "term": term, "reading": deps.validate_reading(reading), "userEdited": True,
        "projectScopeOrigin": "manual",
    })
    if locked is not None:
        entry["locked"] = locked


def _ensure_unique_project_manual_term(project: dict[str, Any], term: str, except_id: str) -> None:
    key = deps.pronunciation_term_key(term.strip())
    if any(entry.get("source") == "manual" and deps.pronunciation_term_key(str(entry.get("term", ""))) == key and str(entry.get("id", "")) != except_id for entry in project.get("pronunciationDictionary", []) if isinstance(entry, dict)):
        raise HTTPException(status_code=422, detail="同じ語句はPROJECTの手動辞書に一件だけ登録できます。")


def _toggle_scope(project: dict[str, Any], request: deps.PronunciationChangeRequest) -> None:
    global_entries = deps.read_pronunciation_dictionary()
    project_entries = [entry for entry in project.get("pronunciationDictionary", []) if isinstance(entry, dict)]
    if request.scope == "project":
        source = next((entry for entry in global_entries if str(entry.get("id", "")) == request.global_id), None)
        deps.change_project_pronunciation(project, entry_id=request.project_id, source_entry=source, enabled=request.enabled, replace_conflict=request.replace_conflict)
        deps.write_project(project)
        return
    if not request.enabled:
        deps.write_pronunciation_dictionary([entry for entry in global_entries if str(entry.get("id", "")) != request.global_id])
        return
    source = next((entry for entry in project_entries if str(entry.get("id", "")) == request.project_id), None)
    if source is None:
        raise HTTPException(status_code=404, detail="PROJECTの辞書項目が見つかりません。")
    conflicts = [entry for entry in global_entries if entry.get("source") == source.get("source") and deps.pronunciation_term_key(str(entry.get("term", ""))) == deps.pronunciation_term_key(str(source.get("term", "")))]
    if any(deps.pronunciation_entry_identity(entry) == deps.pronunciation_entry_identity(source) for entry in conflicts):
        return
    if conflicts and not request.replace_conflict:
        raise HTTPException(status_code=409, detail="SCENAに同じ語句の異なる読みがあります。")
    if conflicts:
        global_entries = [entry for entry in global_entries if entry not in conflicts]
    global_entries.append({**source, "id": deps.new_id("pronunciation")})
    deps.write_pronunciation_dictionary(global_entries)


@deps.app.get("/api/pronunciation-dictionary")
def get_pronunciation_dictionary(suggest_readings: bool = True) -> list[dict[str, Any]]:
    return deps.scoped_pronunciation_rows(deps.read_project())


@deps.app.post("/api/pronunciation-dictionary/cast-suggest")
def suggest_cast_pronunciation_readings() -> list[dict[str, Any]]:
    return deps.track_default_llm_usage("キャスト発音提案", deps.suggest_cast_pronunciation_readings)


@deps.app.post("/api/pronunciation-dictionary/cast")
def add_cast_pronunciation_dictionary_entry(request: deps.CastPronunciationEntryRequest) -> dict[str, Any]:
    return deps.add_cast_pronunciation_entry(request.character_id, request.term, request.reading)


@deps.app.delete("/api/pronunciation-dictionary/cast/{entry_id}")
def delete_cast_pronunciation_dictionary_entry(entry_id: str) -> dict[str, bool]:
    deps.delete_manual_cast_pronunciation_entry(entry_id)
    return {"ok": True}


@deps.app.post("/api/pronunciation-dictionary/suggest")
def suggest_manual_pronunciation_readings() -> list[dict[str, Any]]:
    return deps.track_default_llm_usage("発音提案", deps.suggest_manual_pronunciation_readings)


@deps.app.post("/api/pronunciation-dictionary")
def add_pronunciation_dictionary_entry(request: deps.ManualPronunciationEntryRequest) -> dict[str, Any]:
    return deps.add_manual_pronunciation_entry(request.term, request.reading)


@deps.app.patch("/api/pronunciation-dictionary/{entry_id}")
def update_pronunciation_dictionary_entry(
    entry_id: str, request: deps.ManualPronunciationEntryRequest
) -> dict[str, Any]:
    return deps.update_manual_pronunciation_entry(entry_id, request.term, request.reading)


@deps.app.patch("/api/pronunciation-dictionary/{entry_id}/reading")
def update_cast_pronunciation_dictionary_reading(
    entry_id: str, request: deps.CastPronunciationReadingRequest
) -> dict[str, Any]:
    return deps.update_cast_pronunciation_reading(entry_id, request.reading)


@deps.app.patch("/api/pronunciation-dictionary/{entry_id}/lock")
def update_pronunciation_dictionary_lock(
    entry_id: str, request: deps.PronunciationLockRequest
) -> dict[str, Any]:
    return deps.set_pronunciation_lock(entry_id, request.locked)


@deps.app.delete("/api/pronunciation-dictionary/{entry_id}")
def delete_pronunciation_dictionary_entry(entry_id: str) -> dict[str, bool]:
    deps.delete_manual_pronunciation_entry(entry_id)
    return {"ok": True}


deps.register(__name__, ["get_pronunciation_dictionary"])

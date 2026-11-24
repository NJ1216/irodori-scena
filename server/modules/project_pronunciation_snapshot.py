"""Project-scoped snapshots for otherwise app-wide pronunciation entries."""

from __future__ import annotations

from server.app_deps import Any, HTTPException
from server.registry import deps


def project_cast_ids(project: dict[str, Any]) -> set[str]:
    return {
        str(line.get("characterId", ""))
        for scene in project.get("scenes", [])
        if isinstance(scene, dict)
        for line in scene.get("lines", [])
        if isinstance(line, dict) and str(line.get("characterId", ""))
    }


def project_pronunciation_snapshot(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Preserve project entries and refresh participating cast snapshots."""
    cast_ids = project_cast_ids(project)
    existing = [dict(entry) for entry in project.get("pronunciationDictionary", []) if isinstance(entry, dict)]
    global_cast = [
        dict(entry) for entry in deps.read_pronunciation_dictionary()
        if entry.get("source") == "cast" and str(entry.get("characterId", "")) in cast_ids
    ]
    retained = [entry for entry in existing if entry.get("source") != "cast"]
    by_identity = {deps.pronunciation_entry_identity(entry): entry for entry in retained}
    for entry in global_cast:
        by_identity.setdefault(deps.pronunciation_entry_identity(entry), entry)
    return list(by_identity.values())


def promote_project_pronunciations(project: dict[str, Any], global_ids: set[str]) -> None:
    """Copy only global manual entries actually selected by successful synthesis."""
    if not global_ids:
        return
    snapshot = [dict(entry) for entry in project.get("pronunciationDictionary", []) if isinstance(entry, dict)]
    identities = {deps.pronunciation_entry_identity(entry) for entry in snapshot}
    for entry in deps.read_pronunciation_dictionary():
        if entry.get("source") != "manual" or str(entry.get("id", "")) not in global_ids:
            continue
        identity = deps.pronunciation_entry_identity(entry)
        if identity not in identities:
            snapshot.append({**entry, "id": deps.new_id("pronunciation"), "projectScopeOrigin": "script-auto"})
            identities.add(identity)
    project["pronunciationDictionary"] = snapshot


def merge_generated_pronunciations(latest: dict[str, Any], before: list[dict[str, Any]], generated: dict[str, Any]) -> None:
    """Publish only new promotions; concurrent project dictionary edits win."""
    previous = {deps.pronunciation_entry_identity(entry) for entry in before}
    entries = list(latest.get("pronunciationDictionary", []))
    occupied = {(entry.get("source"), deps.pronunciation_term_key(str(entry.get("term", "")))) for entry in entries}
    for entry in generated.get("pronunciationDictionary", []):
        if entry.get("source") != "manual" or entry.get("projectScopeOrigin") != "script-auto":
            continue
        term = (entry["source"], deps.pronunciation_term_key(str(entry.get("term", ""))))
        if deps.pronunciation_entry_identity(entry) not in previous and term not in occupied:
            entries.append(dict(entry))
            occupied.add(term)
    latest["pronunciationDictionary"] = entries


def script_pronunciation_signature(project: dict[str, Any]) -> list[tuple[Any, ...]]:
    """Return only saved script fields that can change pronunciation use."""
    return [
        (
            str(line.get("id", "")),
            str(line.get("characterId", "")),
            str(line.get("text", "")),
            line.get("pronunciations"),
        )
        for scene in project.get("scenes", [])
        if isinstance(scene, dict)
        for line in scene.get("lines", [])
        if isinstance(line, dict)
    ]


def reconcile_script_pronunciations(project: dict[str, Any], *, add_only: bool = False) -> bool:
    """Synchronize global manual entries selected by the saved script."""
    entries = [dict(entry) for entry in project.get("pronunciationDictionary", []) if isinstance(entry, dict)]
    global_manual = [
        dict(entry) for entry in deps.read_pronunciation_dictionary()
        if entry.get("source") == "manual"
    ]
    removable = [entry for entry in entries if entry.get("projectScopeOrigin") == "script-auto"]
    manual_project = [entry for entry in entries if entry.get("projectScopeOrigin") != "script-auto"]
    candidates = [
        *({**entry, "scope": "project"} for entry in manual_project),
        *({**entry, "scope": "global"} for entry in global_manual),
    ]
    active_character_ids = {
        str(line.get("characterId", ""))
        for scene in project.get("scenes", []) if isinstance(scene, dict)
        for line in scene.get("lines", []) if isinstance(line, dict)
        if str(line.get("characterId", ""))
    }
    used_global_ids: set[str] = set()
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []) if isinstance(scene, dict) else []:
            if not isinstance(line, dict):
                continue
            _, used = deps.resolve_line_pronunciations(
                str(line.get("text", "")), line.get("pronunciations"),
                str(line.get("characterId", "")), active_character_ids, candidates,
            )
            used_global_ids.update(used)

    global_by_id = {str(entry.get("id", "")): entry for entry in global_manual}
    desired = [global_by_id[entry_id] for entry_id in used_global_ids if entry_id in global_by_id]
    next_entries = list(entries)
    if not add_only:
        global_identities = {deps.pronunciation_entry_identity(entry) for entry in global_manual}
        desired_identities = {deps.pronunciation_entry_identity(entry) for entry in desired}
        next_entries = [
            entry for entry in next_entries
            if entry not in removable
            or deps.pronunciation_entry_identity(entry) not in global_identities
            or deps.pronunciation_entry_identity(entry) in desired_identities
        ]
    identities = {deps.pronunciation_entry_identity(entry) for entry in next_entries}
    for entry in desired:
        identity = deps.pronunciation_entry_identity(entry)
        if identity not in identities:
            next_entries.append({**entry, "id": deps.new_id("pronunciation"), "projectScopeOrigin": "script-auto"})
            identities.add(identity)
    if next_entries == entries:
        return False
    project["pronunciationDictionary"] = next_entries
    return True


def change_project_pronunciation(
    project: dict[str, Any], *, entry_id: str, source_entry: dict[str, Any] | None = None,
    enabled: bool = True, replace_conflict: bool = False,
) -> None:
    entries = [dict(entry) for entry in project.get("pronunciationDictionary", []) if isinstance(entry, dict)]
    if not enabled:
        project["pronunciationDictionary"] = [entry for entry in entries if str(entry.get("id", "")) != entry_id]
        return
    if source_entry is None:
        raise HTTPException(status_code=404, detail="複製元の辞書項目が見つかりません。")
    term_key = deps.pronunciation_term_key(str(source_entry.get("term", "")))
    conflicts = [entry for entry in entries if entry.get("source") == source_entry.get("source") and deps.pronunciation_term_key(str(entry.get("term", ""))) == term_key]
    if conflicts and not any(deps.pronunciation_entry_identity(entry) == deps.pronunciation_entry_identity(source_entry) for entry in conflicts):
        if not replace_conflict:
            raise HTTPException(status_code=409, detail="PROJECTに同じ語句の異なる読みがあります。")
        entries = [entry for entry in entries if entry not in conflicts]
    matching = next(
        (entry for entry in entries if deps.pronunciation_entry_identity(entry) == deps.pronunciation_entry_identity(source_entry)),
        None,
    )
    if matching is None:
        entries.append({**source_entry, "id": deps.new_id("pronunciation"), "projectScopeOrigin": "manual"})
    else:
        matching["projectScopeOrigin"] = "manual"
    project["pronunciationDictionary"] = entries


deps.register(__name__, [
    "change_project_pronunciation", "project_cast_ids", "project_pronunciation_snapshot",
    "promote_project_pronunciations", "reconcile_script_pronunciations",
    "script_pronunciation_signature", "merge_generated_pronunciations",
])

"""App-wide pronunciation dictionary and the narrow TTS text boundary."""

from __future__ import annotations

from functools import wraps
from threading import RLock
from uuid import uuid4

from server.app_deps import json, re, Path, Any, HTTPException
from server.registry import deps


_dictionary_lock = RLock()


def dictionary_transaction(function):
    """Keep a SCENA dictionary read, mutation and replacement together."""
    @wraps(function)
    def locked(*args, **kwargs):
        with _dictionary_lock:
            return function(*args, **kwargs)
    return locked

def _pronunciation_debug(message: str) -> None:
    """Emit only content-free development diagnostics."""
    if deps.DEVELOPMENT_MODE_ENABLED:
        print(f"[pronunciation] {message}", flush=True)


pronunciation_debug = _pronunciation_debug


def dictionary_file() -> Path:
    return deps.DATA_ROOT / "pronunciation-dictionary.json"


def validate_reading(value: object) -> str:
    reading = str(value or "").strip()
    if any(character in reading for character in ("\r", "\n")) or any(ord(character) < 32 and character != "\t" for character in reading):
        raise HTTPException(status_code=422, detail="読みに改行や制御文字は使用できません。")
    return reading


def pronunciation_term_key(term: str) -> str:
    return term.casefold()


def pronunciation_entry_identity(entry: dict[str, Any]) -> tuple[Any, ...]:
    """Compare persisted meaning without coupling project and global IDs."""
    return (
        pronunciation_term_key(str(entry.get("term", "")).strip()),
        str(entry.get("reading", "")),
        entry.get("source", "manual"),
        str(entry.get("characterId") or ""),
        tuple(sorted(str(key) for key in entry.get("sourceKeys", []))),
        bool(entry.get("locked", False)),
        bool(entry.get("userEdited", False)),
    )


def read_pronunciation_dictionary() -> list[dict[str, Any]]:
    # This is deliberately a side-effect-free read.  Startup may create the
    # initial project, which snapshots this dictionary; calling
    # ``ensure_data_root`` here would re-enter that creation path forever.
    try:
        value = json.loads(dictionary_file().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=500, detail=f"読み辞書を読み込めませんでした: {error}") from error
    return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []


def write_pronunciation_dictionary(entries: list[dict[str, Any]]) -> None:
    path = dictionary_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        with temporary.open("x", encoding="utf-8") as output:
            output.write(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")
            output.flush()
        json.loads(temporary.read_text(encoding="utf-8"))
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def public_pronunciation_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": entry.get("id"),
        "term": entry.get("term", ""),
        "reading": entry.get("reading", ""),
        "source": entry.get("source", "manual"),
        "characterId": entry.get("characterId"),
        "sourceKeys": entry.get("sourceKeys", []),
        "suggestedReading": entry.get("suggestedReading", ""),
        "userEdited": bool(entry.get("userEdited", False)),
        "locked": bool(entry.get("locked", False)),
    }


def list_pronunciation_dictionary(suggest_readings: bool = True) -> list[dict[str, Any]]:
    return [public_pronunciation_entry(entry) for entry in read_pronunciation_dictionary()]


def scoped_pronunciation_rows(project: dict[str, Any]) -> list[dict[str, Any]]:
    """Return UI rows, merging equal global/project records but retaining conflicts."""
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for scope, entries in (
        ("global", read_pronunciation_dictionary()),
        ("project", project.get("pronunciationDictionary", [])),
    ):
        for raw in entries if isinstance(entries, list) else []:
            if not isinstance(raw, dict):
                continue
            identity = pronunciation_entry_identity(raw)
            row = grouped.setdefault(identity, {**public_pronunciation_entry(raw), "scopes": [], "globalId": None, "projectId": None})
            row["scopes"].append(scope)
            row[f"{scope}Id"] = raw.get("id")
    rows = list(grouped.values())
    term_counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("source")), pronunciation_term_key(str(row.get("term", ""))))
        term_counts[key] = term_counts.get(key, 0) + 1
    for row in rows:
        key = (str(row.get("source")), pronunciation_term_key(str(row.get("term", ""))))
        row["merged"] = len(row["scopes"]) == 2
        row["hasDifferentVersion"] = term_counts[key] > 1
    return rows


def combined_pronunciation_entries(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *({**entry, "scope": "project"} for entry in project.get("pronunciationDictionary", []) if isinstance(entry, dict)),
        *({**entry, "scope": "global"} for entry in read_pronunciation_dictionary()),
    ]


@dictionary_transaction
def add_manual_pronunciation_entry(term: str, reading: str) -> dict[str, Any]:
    term, reading = term.strip(), validate_reading(reading)
    if not term:
        raise HTTPException(status_code=422, detail="語句を入力してください。")
    entries = read_pronunciation_dictionary()
    ensure_unique_manual_term(entries, term)
    entry = {
        "id": deps.new_id("pronunciation"),
        "term": term,
        "reading": reading,
        "source": "manual",
        "characterId": None,
        "sourceKeys": ["manual"],
        "suggestedReading": reading,
        "userEdited": True,
    }
    entries.append(entry)
    write_pronunciation_dictionary(entries)
    return public_pronunciation_entry(entry)


@dictionary_transaction
def update_manual_pronunciation_entry(entry_id: str, term: str, reading: str) -> dict[str, Any]:
    entries = read_pronunciation_dictionary()
    entry = next((item for item in entries if item.get("id") == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="辞書項目が見つかりません。")
    if entry.get("source") != "manual":
        raise HTTPException(status_code=422, detail="キャスト由来の語句は読みだけ編集できます。")
    term = term.strip()
    if not term:
        raise HTTPException(status_code=422, detail="語句を入力してください。")
    ensure_unique_manual_term(entries, term, except_id=entry_id)
    entry.update({"term": term, "reading": validate_reading(reading), "userEdited": True})
    write_pronunciation_dictionary(entries)
    return public_pronunciation_entry(entry)


def ensure_unique_manual_term(entries: list[dict[str, Any]], term: str, *, except_id: str | None = None) -> None:
    key = pronunciation_term_key(term)
    if any(item.get("source") == "manual" and pronunciation_term_key(str(item.get("term", ""))) == key and item.get("id") != except_id for item in entries):
        raise HTTPException(status_code=422, detail="同じ語句は手動辞書に一件だけ登録できます。")


@dictionary_transaction
def update_cast_pronunciation_reading(entry_id: str, reading: str) -> dict[str, Any]:
    entries = read_pronunciation_dictionary()
    entry = next((item for item in entries if item.get("id") == entry_id), None)
    if entry is None or entry.get("source") != "cast":
        raise HTTPException(status_code=404, detail="キャスト由来の辞書項目が見つかりません。")
    entry.update({"reading": validate_reading(reading), "userEdited": True})
    write_pronunciation_dictionary(entries)
    return public_pronunciation_entry(entry)


@dictionary_transaction
def set_pronunciation_lock(entry_id: str, locked: bool) -> dict[str, Any]:
    entries = read_pronunciation_dictionary()
    entry = next((item for item in entries if item.get("id") == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="辞書項目が見つかりません。")
    entry["locked"] = locked
    write_pronunciation_dictionary(entries)
    return public_pronunciation_entry(entry)


@dictionary_transaction
def suggest_cast_pronunciation_readings() -> list[dict[str, Any]]:
    entries = read_pronunciation_dictionary()
    if not any(entry.get("source") == "cast" and entry.get("term") and not entry.get("reading") and not entry.get("locked") for entry in entries):
        return [public_pronunciation_entry(entry) for entry in entries]
    if not deps.default_llm_card_id():
        raise HTTPException(status_code=422, detail="LLMのモデルを接続ページで設定してください。")
    characters = {str(character.get("id", "")): character for character in deps.read_project().get("characters", []) if isinstance(character, dict)}
    for character_id, character in characters.items():
        unknown = [str(entry["term"]) for entry in entries if entry.get("source") == "cast" and str(entry.get("characterId", "")) == character_id and entry.get("term") and not entry.get("reading") and not entry.get("locked")]
        suggestions = _llm_reading_suggestions(character, unknown, [], [])
        for entry in entries:
            if entry.get("source") == "cast" and str(entry.get("characterId", "")) == character_id and not entry.get("reading") and not entry.get("locked"):
                suggestion = suggestions.get(str(entry.get("term", "")))
                if suggestion:
                    entry["reading"] = suggestion
                    entry["suggestedReading"] = suggestion
    write_pronunciation_dictionary(entries)
    return [public_pronunciation_entry(entry) for entry in entries]


@dictionary_transaction
def add_cast_pronunciation_entry(character_id: str, term: str, reading: str) -> dict[str, Any]:
    term, reading = term.strip(), validate_reading(reading)
    characters = {str(character.get("id", "")) for character in deps.read_project().get("characters", []) if isinstance(character, dict)}
    if character_id not in characters:
        raise HTTPException(status_code=404, detail="キャストが見つかりません。")
    if not term:
        raise HTTPException(status_code=422, detail="語句を入力してください。")
    entries = read_pronunciation_dictionary()
    if any(entry.get("source") == "cast" and str(entry.get("characterId", "")) == character_id and pronunciation_term_key(str(entry.get("term", ""))) == pronunciation_term_key(term) for entry in entries):
        raise HTTPException(status_code=422, detail="このキャストには同じ語句が登録されています。")
    entry = {
        "id": deps.new_id("pronunciation"),
        "term": term,
        "reading": reading,
        "source": "cast",
        "characterId": character_id,
        "sourceKeys": ["manual"],
        "suggestedReading": reading,
        "userEdited": True,
    }
    entries.append(entry)
    write_pronunciation_dictionary(entries)
    return public_pronunciation_entry(entry)


@dictionary_transaction
def suggest_manual_pronunciation_readings() -> list[dict[str, Any]]:
    entries = read_pronunciation_dictionary()
    terms = [str(entry.get("term", "")) for entry in entries if entry.get("source") == "manual" and entry.get("term") and not entry.get("reading") and not entry.get("locked")]
    if terms and not deps.default_llm_card_id():
        raise HTTPException(status_code=422, detail="LLMのモデルを接続ページで設定してください。")
    _pronunciation_debug(f"manual reading suggestion requested: count={len(terms)}")
    suggestions = _llm_reading_suggestions({"name": "手動辞書"}, terms, [], [])
    _pronunciation_debug(f"manual reading suggestions accepted: count={len(suggestions)}")
    for entry in entries:
        suggestion = suggestions.get(str(entry.get("term", "")))
        if entry.get("source") == "manual" and not entry.get("reading") and not entry.get("locked") and suggestion:
            entry["reading"] = suggestion
            entry["suggestedReading"] = suggestion
    write_pronunciation_dictionary(entries)
    return [public_pronunciation_entry(entry) for entry in entries]


@dictionary_transaction
def delete_manual_pronunciation_entry(entry_id: str) -> None:
    entries = read_pronunciation_dictionary()
    entry = next((item for item in entries if item.get("id") == entry_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="辞書項目が見つかりません。")
    if entry.get("source") != "manual":
        raise HTTPException(status_code=422, detail="キャスト由来の辞書項目はキャストから削除してください。")
    write_pronunciation_dictionary([item for item in entries if item.get("id") != entry_id])


@dictionary_transaction
def delete_manual_cast_pronunciation_entry(entry_id: str) -> None:
    entries = read_pronunciation_dictionary()
    entry = next((item for item in entries if item.get("id") == entry_id), None)
    if entry is None or entry.get("source") != "cast" or "manual" not in entry.get("sourceKeys", []):
        raise HTTPException(status_code=404, detail="手動追加したキャスト語が見つかりません。")
    write_pronunciation_dictionary([item for item in entries if item.get("id") != entry_id])


def _llm_reading_suggestions(
    character: dict[str, Any],
    unknown_terms: list[str],
    profile_spoken_terms: list[str],
    profile_candidate_terms: list[str],
) -> dict[str, str]:
    return deps.llm_reading_suggestions(character, unknown_terms, profile_spoken_terms, profile_candidate_terms, _request_llm_reading_suggestions)


def _request_llm_reading_suggestions(
    settings: dict[str, Any],
    character: dict[str, Any],
    unknown_terms: list[str],
    profile_spoken_terms: list[str],
    profile_candidate_terms: list[str],
) -> dict[str, str]:
    return deps.request_llm_reading_suggestions(settings, character, unknown_terms, profile_spoken_terms, profile_candidate_terms)


@dictionary_transaction
def reconcile_cast_pronunciations(characters: list[dict[str, Any]]) -> None:
    """Deterministically make cast entries match the four supported profile fields."""
    characters = [item for item in characters if isinstance(item, dict) and str(item.get("id", ""))]
    entries = read_pronunciation_dictionary()
    retained = [item for item in entries if item.get("source") != "cast" and "script" not in item.get("sourceKeys", [])]
    for character in characters:
        character_id = str(character["id"])
        existing = {str(item.get("term", "")): item for item in entries if item.get("source") == "cast" and str(item.get("characterId", "")) == character_id}
        manual = [item for item in existing.values() if "manual" in item.get("sourceKeys", [])]
        retained.extend(manual)
        for term, (suggestion, keys) in deps.cast_words(character).items():
            if any(pronunciation_term_key(str(item.get("term", ""))) == pronunciation_term_key(term) for item in manual):
                continue
            entry = existing.get(term)
            if entry is None or "manual" in entry.get("sourceKeys", []):
                entry = {
                    "id": deps.new_id("pronunciation"),
                    "term": term,
                    "reading": suggestion,
                    "source": "cast",
                    "characterId": character_id,
                    "userEdited": False,
                }
            entry["sourceKeys"], entry["suggestedReading"] = sorted(keys), suggestion
            if not entry.get("userEdited") and not entry.get("locked"):
                entry["reading"] = suggestion
            retained.append(entry)
    # Entries for removed casts, including their manually added cast terms, are omitted.
    write_pronunciation_dictionary(retained)


def pronunciation_characters(
    project: dict[str, Any], updated_character: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return every known cast once, with project and pending edits taking precedence."""
    by_id: dict[str, dict[str, Any]] = {}
    for character in [*deps.read_global_characters(), *project.get("characters", [])]:
        if isinstance(character, dict) and str(character.get("id", "")):
            by_id[str(character["id"])] = character
    if updated_character is not None and str(updated_character.get("id", "")):
        by_id[str(updated_character["id"])] = updated_character
    return list(by_id.values())


def sync_character_pronunciations(character: dict[str, Any], *, suggest_readings: bool = False) -> None:
    project = deps.read_project()
    reconcile_cast_pronunciations(pronunciation_characters(project, character))


@dictionary_transaction
def remove_character_pronunciations(character_id: str) -> None:
    write_pronunciation_dictionary([entry for entry in read_pronunciation_dictionary() if not (entry.get("source") == "cast" and entry.get("characterId") == character_id)])


def apply_pronunciation_dictionary(
    text: str,
    character_id: str,
    active_character_ids: set[str] | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> str:
    entries = read_pronunciation_dictionary() if entries is None else entries
    candidates_by_term: dict[str, list[tuple[int, str, str, dict[str, Any]]]] = {}
    for entry in entries:
        term, reading = str(entry.get("term", "")), str(entry.get("reading", ""))
        if not term or not reading:
            continue
        rank = _pronunciation_candidate_rank(entry, character_id, active_character_ids or set())
        if rank is not None:
            owner_id = str(entry.get("characterId", "")) if entry.get("source") == "cast" else ""
            stable_id = str(entry.get("id", ""))
            candidates_by_term.setdefault(pronunciation_term_key(term), []).append((rank, owner_id, stable_id, entry))
    chosen = [min(candidates, key=lambda candidate: candidate[:3])[3] for candidates in candidates_by_term.values()]
    for entry in sorted(chosen, key=lambda item: (-len(str(item["term"])), pronunciation_term_key(str(item["term"])))):
        term, reading = str(entry["term"]), str(entry["reading"])
        text = re.sub(re.escape(term), reading, text, flags=re.IGNORECASE) if re.search(r"[A-Za-z]", term) else text.replace(term, reading)
    return text


def resolve_pronunciation_dictionary(
    text: str,
    character_id: str,
    active_character_ids: set[str] | None,
    entries: list[dict[str, Any]],
) -> tuple[str, set[str]]:
    """Resolve project before global and report global manual IDs actually used."""
    candidates: dict[str, list[tuple[int, int, str, str, dict[str, Any]]]] = {}
    for entry in entries:
        term, reading = str(entry.get("term", "")), str(entry.get("reading", ""))
        rank = _pronunciation_candidate_rank(entry, character_id, active_character_ids or set())
        if not term or not reading or rank is None:
            continue
        scope_rank = 0 if entry.get("scope") == "project" else 1
        owner = str(entry.get("characterId", "")) if entry.get("source") == "cast" else ""
        candidates.setdefault(pronunciation_term_key(term), []).append((scope_rank, rank, owner, str(entry.get("id", "")), entry))
    chosen = [min(values, key=lambda value: value[:4])[4] for values in candidates.values()]
    used: set[str] = set()
    for entry in sorted(chosen, key=lambda item: (-len(str(item["term"])), pronunciation_term_key(str(item["term"])))):
        term, reading = str(entry["term"]), str(entry["reading"])
        pattern = re.compile(re.escape(term), re.IGNORECASE) if re.search(r"[A-Za-z]", term) else None
        if pattern:
            text, count = pattern.subn(reading, text)
        else:
            count = text.count(term)
            text = text.replace(term, reading)
        if count and entry.get("scope") == "global" and entry.get("source") == "manual":
            used.add(str(entry.get("id", "")))
    return text, used


def _pronunciation_candidate_rank(entry: dict[str, Any], speaker_id: str, active_character_ids: set[str]) -> int | None:
    """Return the product precedence for one usable dictionary candidate."""
    source = entry.get("source")
    if source == "manual":
        return 0
    if source != "cast":
        return None
    source_keys = set(entry.get("sourceKeys", []))
    if "manual" in source_keys:
        return 1
    owner_id = str(entry.get("characterId", ""))
    if "firstPerson" in source_keys and owner_id == speaker_id:
        return 2
    name_keys = {"displayName", "familyName", "givenName"}
    # Legacy cast entries may lack sourceKeys; keep their former global,
    # name-like behavior for compatibility.
    if source_keys and not source_keys.intersection(name_keys):
        return None
    if owner_id == speaker_id:
        return 3
    return 4 if owner_id in active_character_ids else 5


def affected_pronunciation_line_ids(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    project = deps.read_project()
    active_character_ids = {str(line.get("characterId", "")) for scene in project.get("scenes", []) if isinstance(scene, dict) for line in scene.get("lines", []) if isinstance(line, dict) if str(line.get("characterId", ""))}
    affected: list[str] = []
    for scene in project.get("scenes", []):
        for line in scene.get("lines", []) if isinstance(scene, dict) else []:
            if not isinstance(line, dict) or line.get("enabled") is False:
                continue
            text, character_id = str(line.get("text", "")), str(line.get("characterId", ""))
            selected_id = str(line.get("selectedTakeId") or "")
            selected_exists = any(isinstance(take, dict) and str(take.get("id", "")) == selected_id for take in line.get("takes", []))
            if not text.strip() or not character_id or not selected_exists:
                continue
            old = deps.resolve_line_pronunciations(text, line.get("pronunciations"), character_id, active_character_ids, before)[0]
            new = deps.resolve_line_pronunciations(text, line.get("pronunciations"), character_id, active_character_ids, after)[0]
            if old != new and line.get("id"):
                affected.append(str(line["id"]))
    return affected


deps.register(
    __name__,
    [
        "add_cast_pronunciation_entry",
        "add_manual_pronunciation_entry",
        "affected_pronunciation_line_ids",
        "apply_pronunciation_dictionary",
        "delete_manual_cast_pronunciation_entry",
        "delete_manual_pronunciation_entry",
        "list_pronunciation_dictionary",
        "read_pronunciation_dictionary",
        "reconcile_cast_pronunciations",
        "remove_character_pronunciations",
        "sync_character_pronunciations",
        "combined_pronunciation_entries",
        "pronunciation_characters",
        "pronunciation_entry_identity",
        "resolve_pronunciation_dictionary",
        "scoped_pronunciation_rows",
        "dictionary_file",
        "ensure_unique_manual_term",
        "pronunciation_term_key",
        "public_pronunciation_entry",
        "set_pronunciation_lock",
        "suggest_cast_pronunciation_readings",
        "suggest_manual_pronunciation_readings",
        "update_cast_pronunciation_reading",
        "update_manual_pronunciation_entry",
        "validate_reading",
        "write_pronunciation_dictionary",
        "pronunciation_debug",
    ],
)

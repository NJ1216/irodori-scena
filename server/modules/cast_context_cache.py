from __future__ import annotations

from server.app_deps import hashlib, json, Path, Any
from server.registry import deps


PROMPT_VERSION = "scena-cast-summary-v1"
MAX_CAST_JSON_CHARACTERS = 2000


def _cache_path() -> Path:
    return deps.DATA_ROOT / "cache" / "cast-context-summaries.json"


def _read_cache() -> dict[str, Any]:
    try:
        value = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "entries": {}}
    if not isinstance(value, dict) or not isinstance(value.get("entries"), dict):
        return {"version": 1, "entries": {}}
    return value


def _write_cache(cache: dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    temporary.replace(path)


def cast_context_scope(character: dict[str, Any], project_id: str) -> str:
    character_id = str(character.get("id", "")).strip()
    return f"global:{character_id}" if character.get("scope") == "global" else f"project:{project_id}:{character_id}"


def character_context_fingerprint(character: dict[str, Any]) -> str:
    content = {
        "name": str(character.get("name", "")).strip(),
        "profile": str(character.get("profile", "")).strip(),
        "profileDetails": deps.normalize_character_profile_details(character.get("profileDetails")),
    }
    encoded = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _exact_profile(details: dict[str, Any]) -> dict[str, Any]:
    fields = ("familyName", "familyNameKana", "givenName", "givenNameKana", "aliases", "firstPerson",
              "secondPerson", "defaultAddressBasis", "defaultHonorific", "defaultAddressNote")
    return {field: details[field] for field in fields if details.get(field)}


def _relation_exact(character: dict[str, Any], selected: dict[str, dict[str, Any]], aliases) -> list[dict[str, Any]]:
    details = deps.normalize_character_profile_details(character.get("profileDetails"))
    rows = []
    for target_id, relation in details.get("castRelations", {}).items():
        target = selected.get(str(target_id))
        if not target or not isinstance(relation, dict):
            continue
        rows.append({
            "target": aliases.get(str(target_id), str(target_id)),
            "name": str(target.get("name", "")).strip(),
            **({"address": str(relation.get("address", "")).strip()} if relation.get("address") else {}),
        })
    return rows


def _trim_sentences(text: str, available: int) -> str:
    if available <= 0:
        return ""
    sentences = [part.strip() for part in text.replace("\n", "。").split("。") if part.strip()]
    result = ""
    for sentence in sentences:
        candidate = result + ("。" if result else "") + sentence
        if len(candidate) > available:
            break
        result = candidate
    return result or text[:available]


def _bounded(item: dict[str, Any]) -> dict[str, Any]:
    def encoded() -> str:
        return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    if len(encoded()) <= MAX_CAST_JSON_CHARACTERS:
        return item
    for relation in item.get("relations", []):
        relation.pop("summary", None)
    if len(encoded()) <= MAX_CAST_JSON_CHARACTERS:
        return item
    item["summary"] = _trim_sentences(str(item.get("summary", "")), max(0, MAX_CAST_JSON_CHARACTERS - len(encoded()) + len(str(item.get("summary", "")))))
    while len(encoded()) > MAX_CAST_JSON_CHARACTERS and item.get("summary"):
        item["summary"] = str(item["summary"])[:-16]
    if len(encoded()) > MAX_CAST_JSON_CHARACTERS:
        item.pop("summary", None)
    return item


def _fallback(character: dict[str, Any]) -> str:
    details = deps.normalize_character_profile_details(character.get("profileDetails"))
    values = [str(character.get("profile", "")).strip()]
    for field in ("personality", "speechStyle", "role", "background", "likes", "dislikes"):
        if details.get(field):
            values.append(f"{field}:{details[field]}")
    return _trim_sentences("。".join(value for value in values if value), 900)


def _summary_contract(aliases: set[str]):
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "cast": {"type": "string", "enum": sorted(aliases)}, "summary": {"type": "string"},
        "relation_summaries": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "properties": {"target": {"type": "string"}, "summary": {"type": "string"}},
            "required": ["target", "summary"]}},
    }, "required": ["cast", "summary", "relation_summaries"]}
    def legacy(content: str) -> list[dict[str, Any]]:
        rows = []
        for line in content.splitlines():
            cast, separator, summary = line.partition("|")
            if separator and cast.strip() in aliases and summary.strip():
                rows.append({"cast": cast.strip(), "summary": summary.strip(), "relation_summaries": []})
        return rows
    return deps.LlmRecordContract(
        "cast-context-summary", 1, schema, "cast", frozenset(aliases),
        legacy_suffix="各人物を CAST|人物概要 の一行形式で返す。説明、見出し、Markdownは禁止。",
        legacy_parser=legacy,
    )


def _generate_summaries(request: Any, misses: list[dict[str, Any]], input_rows: list[dict[str, Any]],
                        aliases: dict[str, str], job_id: str | None) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        result = deps.complete_records(
            request, contract=_summary_contract({aliases[str(item["id"])] for item in misses}),
            system=("人物設定を台本執筆用に短く要約する。人物ごとに独立して返す。名前、呼称、一人称、二人称は"
                    "要約へ混ぜず、入力の事実だけを保つ。関係要約はtargetごとに返す。"),
            user={"prompt_version": PROMPT_VERSION, "characters": input_rows}, max_tokens=1800,
            temperature=0.2, sampling_policy="deterministic", job_id=job_id)
        return ({str(row.get("cast", "")): row for row in result.records
                 if str(row.get("summary", "")).strip()}, "")
    except Exception as error:
        return {}, f"{type(error).__name__}: {error}"


def _record_summary_usage(job_id: str | None, before: dict[str, int], audit: list[dict[str, Any]],
                          summary_called: bool) -> None:
    if not job_id:
        return
    with deps.DRAFT_JOBS_LOCK:
        job = deps.DRAFT_JOBS.get(job_id)
        if not isinstance(job, dict):
            return
        after = job.get("tokenUsage", {})
        job["castContextSummaryUsage"] = {
            "calls": 1 if summary_called else 0,
            "hits": sum(row["cache"] == "hit" for row in audit),
            "misses": sum(row["cache"] == "miss" for row in audit),
            "fallbacks": sum(bool(row["fallback"]) for row in audit),
            "inputTokens": max(0, int(after.get("inputTokens", 0)) - int(before.get("inputTokens", 0))),
            "outputTokens": max(0, int(after.get("outputTokens", 0)) - int(before.get("outputTokens", 0))),
        }


def compile_cast_context(request: Any, characters: list[dict[str, Any]], *, project_id: str,
                         aliases: dict[str, str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = {str(item.get("id", "")): item for item in characters if str(item.get("id", ""))}
    cache = _read_cache()
    entries = cache["entries"]
    summaries: dict[str, dict[str, Any]] = {}
    audit: list[dict[str, Any]] = []
    misses = []
    for character_id, character in selected.items():
        scope, fingerprint = cast_context_scope(character, project_id), character_context_fingerprint(character)
        entry = entries.get(scope)
        hit = isinstance(entry, dict) and entry.get("fingerprint") == fingerprint and entry.get("promptVersion") == PROMPT_VERSION
        if hit:
            summaries[character_id] = entry
        else:
            misses.append(character)
        audit.append({"cast": aliases.get(character_id, "?"), "scope": scope,
                      "fingerprint": fingerprint, "cache": "hit" if hit else "miss"})
    job_id = getattr(deps.DRAFT_LLM_THREAD_CONTEXT, "job_id", None)
    before_usage: dict[str, int] = {}
    if job_id:
        with deps.DRAFT_JOBS_LOCK:
            before_usage = dict(deps.DRAFT_JOBS.get(job_id, {}).get("tokenUsage", {}))
    llm_misses = [item for item in misses if len(deps.character_llm_profile(item)) > 200]
    summary_called = bool(llm_misses)
    if llm_misses:
        input_rows = []
        for character in llm_misses:
            character_id = str(character.get("id", ""))
            details = deps.normalize_character_profile_details(character.get("profileDetails"))
            input_rows.append({"cast": aliases[character_id], "name": character.get("name", ""),
                               "profile": character.get("profile", ""), "profile_details": details,
                               "relations": _relation_exact(character, selected, aliases)})
        by_alias, summary_error = _generate_summaries(request, llm_misses, input_rows, aliases, job_id)
        if summary_error:
            for row in audit:
                if row["cache"] == "miss":
                    row["summaryError"] = summary_error
        changed = False
        for character in llm_misses:
            character_id, alias = str(character.get("id", "")), aliases[str(character.get("id", ""))]
            row = by_alias.get(alias)
            if not row:
                continue
            scope, fingerprint = cast_context_scope(character, project_id), character_context_fingerprint(character)
            id_by_alias = {value: key for key, value in aliases.items()}
            entry = {"fingerprint": fingerprint, "promptVersion": PROMPT_VERSION,
                     "summary": str(row.get("summary", "")).strip()[:1200],
                     "relations": {id_by_alias.get(str(item.get("target", "")), ""): str(item.get("summary", "")).strip()[:400]
                                   for item in row.get("relation_summaries", []) if isinstance(item, dict)}}
            entries[scope] = summaries[character_id] = entry
            changed = True
        if changed:
            _write_cache(cache)
    context = []
    for character_id, character in selected.items():
        details = deps.normalize_character_profile_details(character.get("profileDetails"))
        summary = summaries.get(character_id)
        relation_summaries = summary.get("relations", {}) if summary else {}
        relations = _relation_exact(character, selected, aliases)
        for relation in relations:
            target_id = next((key for key, value in aliases.items() if value == relation.get("target")), "")
            if target_id in relation_summaries:
                relation["summary"] = relation_summaries[target_id]
        settings = request.cast_settings.get(character_id) if hasattr(request, "cast_settings") else None
        item = {"cast": aliases[character_id], "name": str(character.get("name", "")).strip(),
                "reader_facing_role_seed": str(details.get("role", "")).strip(),
                "reader_facing_introduction_seed": deps.draft_reader_introduction(character),
                "exact_profile": _exact_profile(details),
                "summary": str(summary.get("summary", "")) if summary else _fallback(character),
                "relations": relations,
                "preferences": {
                    "emoji": "許可" if settings and settings.emoji_expressions else "禁止",
                    "fillers": "多めに自然に入れる" if settings and settings.filler_richness else "必要な箇所だけにする",
                    "priority": settings.appearance_priority if settings else "standard",
                }}
        item = _bounded(item)
        context.append(item)
        audit_row = next(row for row in audit if row["cast"] == aliases[character_id])
        audit_row["fallback"] = summary is None
        audit_row["promptCharacters"] = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
    _record_summary_usage(job_id, before_usage, audit, summary_called)
    return context, audit


def invalidate_cast_context(scope: str, character_id: str, project_id: str = "") -> None:
    cache = _read_cache()
    key = f"global:{character_id}" if scope == "global" else f"project:{project_id}:{character_id}"
    if cache["entries"].pop(key, None) is not None:
        _write_cache(cache)


def delete_cast_context(scope: str, character_id: str, project_id: str = "") -> None:
    cache = _read_cache()
    key = f"global:{character_id}" if scope == "global" else f"project:{project_id}:{character_id}"
    changed = cache["entries"].pop(key, None) is not None
    for entry in cache["entries"].values():
        relations = entry.get("relations") if isinstance(entry, dict) else None
        if isinstance(relations, dict) and relations.pop(character_id, None) is not None:
            changed = True
    if changed:
        _write_cache(cache)


deps.register(__name__, ["character_context_fingerprint", "cast_context_scope", "compile_cast_context",
                         "delete_cast_context", "invalidate_cast_context"])

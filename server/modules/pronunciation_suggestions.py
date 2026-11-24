from __future__ import annotations

import re
from types import SimpleNamespace
from typing import Any

from server.registry import deps

KANA_TERM_RE = re.compile(r"^[\u3041-\u3096\u30a1-\u30fa\u30fc]+$")


def normalized_name(value: str) -> str:
    return re.sub(r"\s+", "", value)


def cast_words(character: dict[str, Any]) -> dict[str, tuple[str, set[str]]]:
    details = character.get("profileDetails") if isinstance(character.get("profileDetails"), dict) else {}
    family, given = str(details.get("familyName", "")).strip(), str(details.get("givenName", "")).strip()
    family_kana, given_kana = str(details.get("familyNameKana", "")).strip(), str(details.get("givenNameKana", "")).strip()
    words: dict[str, tuple[str, set[str]]] = {}

    def add(term: str, reading: str, key: str) -> None:
        if not term:
            return
        reading = reading or (term if KANA_TERM_RE.fullmatch(term) else "")
        old = words.get(term)
        words[term] = (old[0] or reading if old else reading, (old[1] if old else set()) | {key})

    display_name, full_name = str(character.get("name", "")).strip(), family + given
    add(family, family_kana, "familyName")
    add(given, given_kana, "givenName")
    if not full_name or normalized_name(display_name) != normalized_name(full_name):
        add(display_name, "", "displayName")
    first_person = details.get("firstPerson", [])
    for value in first_person if isinstance(first_person, list) else [first_person]:
        add(str(value).strip(), "", "firstPerson")
    return words


def llm_reading_suggestions(character: dict[str, Any], unknown_terms: list[str], spoken_terms: list[str], candidate_terms: list[str], request_fn) -> dict[str, str]:
    if not unknown_terms and not spoken_terms and not candidate_terms:
        return {}
    try:
        selected = deps.resolve_default_llm()
        if selected.get("provider") == "scena-local":
            deps.load_local_llm(str(selected["model"]), settings=selected.get("settings") or {})
            selected["baseUrl"], selected["apiKey"] = deps.local_llm_runtime_endpoint(), deps.local_llm_runtime_api_key()
        with deps.PRONUNCIATION_LLM_LOCK:
            return request_fn(selected, character, unknown_terms, spoken_terms, candidate_terms)
    except Exception as error:
        deps.pronunciation_debug(f"LLM reading suggestion failed: {type(error).__name__}: {error}")
        return {}


def request_llm_reading_suggestions(settings: dict[str, Any], character: dict[str, Any], unknown_terms: list[str], spoken_terms: list[str], candidate_terms: list[str]) -> dict[str, str]:
    all_terms = list(dict.fromkeys([*unknown_terms, *spoken_terms, *candidate_terms]))
    aliases = {f"T{index + 1}": term for index, term in enumerate(all_terms)}
    reverse_aliases = {deps.pronunciation_term_key(term): alias for alias, term in aliases.items()}
    prompt = {"character": str(character.get("name", "")), "terms": [{"alias": alias, "term": term, "required": term in unknown_terms or term in spoken_terms} for alias, term in aliases.items()]}
    request = SimpleNamespace(provider=str(settings.get("provider", "openai")), base_url=str(settings.get("baseUrl", "")), model=str(settings.get("model", "")), api_key=str(settings.get("apiKey", "")))
    schema = {"type": "object", "additionalProperties": False, "properties": {"term": {"type": "string", "enum": list(aliases)}, "reading": {"type": "string"}, "properNoun": {"type": "boolean"}}, "required": ["term", "reading", "properNoun"]}

    def legacy_parser(content):
        records, _ = deps.extract_complete_records(content.replace('"entries"', '"records"', 1))
        return [{**item, "term": reverse_aliases[deps.pronunciation_term_key(str(item.get("term", "")).strip())]} for item in records if deps.pronunciation_term_key(str(item.get("term", "")).strip()) in reverse_aliases]

    contract = deps.LlmRecordContract("pronunciation", 1, schema, "term", frozenset(aliases), legacy_suffix="JSON {entries:[{term,reading,properNoun}]} を返し、termには入力表記を使う。", legacy_parser=legacy_parser)
    completion = deps.complete_records(request, contract=contract, system="Give kana readings for required terms. For optional terms include only proper nouns or work-specific terms and omit common nouns. Return the request-local term alias unchanged; reading uses kana only.", user=prompt, max_tokens=min(256, max(64, 32 + 48 * len(all_terms))), temperature=0, sampling_policy="deterministic")
    deps.pronunciation_debug(f"LLM reading response received: characters={len(completion.raw_response)}")
    allowed = {deps.pronunciation_term_key(term): term for term in all_terms}
    required = {deps.pronunciation_term_key(term) for term in [*unknown_terms, *spoken_terms]}
    result: dict[str, str] = {}
    for item in completion.records:
        term, reading = aliases.get(str(item.get("term", "")), ""), str(item.get("reading", "")).strip()
        key = deps.pronunciation_term_key(term)
        if key in allowed and (item.get("properNoun", True) or key in required) and reading:
            result[allowed[key]] = reading
    return result


deps.register(__name__, ["cast_words", "llm_reading_suggestions", "normalized_name", "request_llm_reading_suggestions"])

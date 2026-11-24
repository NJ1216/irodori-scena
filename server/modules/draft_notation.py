from __future__ import annotations

from server.app_deps import json, re, Path, Any, Callable
from server.registry import deps


# These are glyph-only substitutions whose Japanese form is unambiguous.  The
# remaining disallowed glyphs deliberately go through the small reviewed-patch
# request below; a nearest-character substitution is not safe for them.
SAFE_SIMPLIFIED_GLYPH_REPLACEMENTS = {
    "说": "説", "为": "為", "个": "個", "门": "門", "见": "見", "听": "聴", "话": "話",
    "让": "譲", "过": "過", "对": "対", "实": "実", "问": "問", "间": "間", "开": "開",
    "关": "関", "应": "応", "现": "現", "样": "様", "从": "従", "进": "進", "远": "遠",
    "动": "動", "觉": "覚", "认": "認", "给": "給", "带": "帯", "种": "種", "书": "書",
    "车": "車", "东": "東", "长": "長", "难": "難", "无": "無", "乐": "楽", "头": "頭",
    "脸": "顔", "处": "処", "变": "変", "并": "並", "层": "層", "压": "圧", "严": "厳",
    "亲": "親", "纱": "紗", "还": "還",
}
CONTEXTUAL_SIMPLIFIED_GLYPHS = deps.DISALLOWED_SIMPLIFIED_CHINESE - SAFE_SIMPLIFIED_GLYPH_REPLACEMENTS.keys()
PRONOUNS = frozenset(("私", "わたし", "僕", "ぼく", "俺", "おれ", "あたし", "わし", "あなた", "あんた", "きみ", "お前", "おまえ", "貴方", "てめえ", "おたく"))
PRONOUN_EXCLUSIONS = frozenset(("自分", "うち", "我", "君"))


def _protected_ranges(text: str) -> list[range]:
    ranges: list[range] = []
    for opener, closer in (("「", "」"), ("『", "』"), ("“", "”")):
        start = 0
        while (open_at := text.find(opener, start)) >= 0:
            close_at = text.find(closer, open_at + 1)
            if close_at < 0:
                break
            ranges.append(range(open_at, close_at + 1))
            start = close_at + 1
    # Do not alter a phrase being repeated or cited without explicit quotes.
    for match in re.finditer(r"[^「」『』“”\n]{0,80}[。！？!?]?(?:って|だって|という)(?:[。！？!?]|$)", text):
        ranges.append(range(match.start(), match.end()))
    return ranges


def _is_protected(index: int, ranges: list[range]) -> bool:
    return any(index in item for item in ranges)


def _allowed_pronouns(characters: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for cast in characters:
        cast_id = str(cast.get("id", ""))
        details = cast.get("profileDetails")
        if not isinstance(details, dict):
            continue
        allowed = {
            str(value).strip()
            for field in ("firstPerson", "secondPerson")
            for value in (details.get(field, []) if isinstance(details.get(field), list) else [])
            if str(value).strip()
        }
        if cast_id and allowed:
            result[cast_id] = allowed
    return result


def _address_collision_rules(characters: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Find unnatural pronoun+honorific joins unless explicitly saved as an address."""
    rules: dict[str, dict[str, str]] = {}
    for cast in characters:
        cast_id = str(cast.get("id", ""))
        details = deps.normalize_character_profile_details(cast.get("profileDetails"))
        second_person = details.get("secondPerson", [])
        honorifics = re.split(r"[／、,，\s]+", str(details.get("defaultHonorific", "")))
        relations = details.get("castRelations", {})
        explicit = {
            str(relation.get("address", "")).strip()
            for relation in relations.values()
            if isinstance(relation, dict) and str(relation.get("address", "")).strip()
        } if isinstance(relations, dict) else set()
        combinations = {
            f"{pronoun}{honorific}": pronoun
            for pronoun in second_person if pronoun in {"あなた", "貴方", "あんた", "きみ", "君"}
            for honorific in honorifics if honorific and f"{pronoun}{honorific}" not in explicit
        }
        if cast_id and combinations:
            rules[cast_id] = combinations
    return rules


def _apply_safe_glyphs(drafted_chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chapters = []
    for item in drafted_chapters:
        lines = []
        for line in item["dialogue"].get("lines", []):
            text = str(line.get("text", ""))
            protected = _protected_ranges(text)
            normalized = "".join(
                SAFE_SIMPLIFIED_GLYPH_REPLACEMENTS.get(character, character)
                if not _is_protected(index, protected) else character
                for index, character in enumerate(text)
            )
            lines.append({**line, "text": normalized})
        dialogue = {**item["dialogue"], "lines": lines}
        chapters.append({**item, "dialogue": dialogue, "spoken": deps.spoken_dialogue_count(dialogue)})
    return chapters


def _candidates(chapters, allowed_by_cast, address_collisions=None):
    candidates = []
    for item in chapters:
        for line in item["dialogue"].get("lines", []):
            text, line_id, cast_id = str(line.get("text", "")), str(line["line_id"]), str(line.get("character_id", ""))
            protected = _protected_ranges(text)
            allowed = allowed_by_cast.get(cast_id, set())
            for index, character in enumerate(text):
                if character in CONTEXTUAL_SIMPLIFIED_GLYPHS and not _is_protected(index, protected):
                    candidates.append({"line": line_id, "speaker": cast_id, "offset": index, "expected": character, "kind": "simplified"})
            if allowed:
                for pronoun in PRONOUNS:
                    if pronoun in PRONOUN_EXCLUSIONS:
                        continue
                    start = text.find(pronoun)
                    while start >= 0:
                        if pronoun not in allowed and not _is_protected(start, protected):
                            candidates.append({"line": line_id, "speaker": cast_id, "offset": start, "expected": pronoun, "kind": "pronoun", "allowed": sorted(allowed)})
                        start = text.find(pronoun, start + len(pronoun))
            for combined, replacement in (address_collisions or {}).get(cast_id, {}).items():
                start = text.find(combined)
                while start >= 0:
                    if not _is_protected(start, protected):
                        candidates.append({
                            "line": line_id, "speaker": cast_id, "offset": start,
                            "expected": combined, "kind": "address", "allowed": [replacement],
                        })
                    start = text.find(combined, start + len(combined))
    return candidates


def _parse_patches(content: str) -> list[dict[str, Any]]:
    patches = []
    for row in content.splitlines():
        match = re.fullmatch(r"(L\d+)\|(\d+)\|([^|]+)\|([^|]*)", row.strip())
        if match:
            line, offset, expected, replacement = match.groups()
            patches.append({"line": line, "offset": int(offset), "expected": expected, "replacement": replacement})
    return patches


def _notation_contract(candidates):
    by_id = {f"P{index + 1}": candidate for index, candidate in enumerate(candidates)}
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "candidate": {"type": "string", "enum": list(by_id)}, "replacement": {"type": "string"},
    }, "required": ["candidate", "replacement"]}
    def legacy(content):
        records = []
        for patch in _parse_patches(content):
            match = next((alias for alias, candidate in by_id.items()
                          if candidate["line"] == patch["line"] and candidate["offset"] == patch["offset"]
                          and candidate["expected"] == patch["expected"]), None)
            if match:
                records.append({"candidate": match, "replacement": patch["replacement"]})
        return records
    return deps.LlmRecordContract(
        "draft-notation", 1, schema, "candidate", frozenset(by_id),
        legacy_suffix="修正できる候補だけをL1|位置|原文|置換の既定形式で返す。", legacy_parser=legacy,
    ), by_id


def _project_notation(records, by_id):
    return "\n".join(
        f"{by_id[row['candidate']]['line']}|{by_id[row['candidate']]['offset']}|"
        f"{by_id[row['candidate']]['expected']}|{row['replacement']}" for row in records
    )


def _validated_patches(chapters, candidates, patches, line_aliases=None):
    candidate_by_key = {(item["line"], item["offset"], item["expected"]): item for item in candidates}
    line_by_id = {str(line["line_id"]): line for item in chapters for line in item["dialogue"].get("lines", [])}
    if line_aliases:
        line_by_id.update(line_aliases)
    valid = []
    for patch in patches:
        candidate = candidate_by_key.get((patch["line"], patch["offset"], patch["expected"]))
        line = line_by_id.get(patch["line"])
        if not candidate or not line or str(line.get("character_id", "")) != candidate["speaker"]:
            continue
        text, expected, replacement = str(line["text"]), patch["expected"], patch["replacement"]
        if text[patch["offset"] : patch["offset"] + len(expected)] != expected:
            continue
        is_valid = replacement in candidate.get("allowed", set()) if candidate.get("allowed") else len(replacement) == 1 and replacement not in deps.DISALLOWED_SIMPLIFIED_CHINESE
        if not is_valid:
            continue
        valid.append(patch)
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for patch in valid:
        grouped.setdefault((patch["line"], patch["offset"]), []).append(patch)
    accepted, conflicts = [], []
    for group in grouped.values():
        unique = {(item["expected"], item["replacement"]) for item in group}
        if len(unique) == 1:
            accepted.append(group[0])
        else:
            conflicts.extend(group)
    return accepted, conflicts, line_by_id


def _apply_patches(chapters, candidates, patches, line_aliases: dict[str, dict[str, Any]] | None = None):
    accepted, _, line_by_id = _validated_patches(chapters, candidates, patches, line_aliases)
    for patch in sorted(accepted, key=lambda item: (item["line"], item["offset"]), reverse=True):
        line = line_by_id[patch["line"]]
        offset, expected = patch["offset"], patch["expected"]
        line["text"] = line["text"][:offset] + patch["replacement"] + line["text"][offset + len(expected) :]
    return accepted


def normalize_draft_notation(request: deps.DraftRequest, *, job_id: str, drafted_chapters, characters: list[dict[str, Any]], cast_alias_by_id, token_budget: int, debug_directory: Path, should_cancel: Callable[[], bool] | None = None):
    """Apply safe glyphs locally, then request at most one verified local patch set."""
    chapters = _apply_safe_glyphs(drafted_chapters)
    candidates = _candidates(chapters, _allowed_pronouns(characters), _address_collision_rules(characters))
    deps.update_draft_job(job_id, phase="notation", message="表記候補を抽出しています", notationCompletedSteps=1, notationTotalSteps=3)
    deps.advance_draft_progress(job_id, overall_progress=deps.DRAFT_PROGRESS_DIALOGUE_END)
    if not candidates:
        deps.update_draft_job(job_id, message="パッチを検証しています", notationCompletedSteps=3)
        deps.advance_draft_progress(job_id, overall_progress=deps.DRAFT_PROGRESS_NOTATION_END)
        return chapters
    deps.update_draft_job(job_id, draftFinishingStepRequired=True)
    candidate_sources = {str(candidate["line"]) for candidate in candidates}
    alias_by_line = {str(line["line_id"]): f"L{index}" for index, line in enumerate(
        (line for item in chapters for line in item["dialogue"].get("lines", [])
         if str(line["line_id"]) in candidate_sources), 1
    )}
    for candidate in candidates:
        candidate["line"] = alias_by_line[candidate["line"]]
    line_sources = {alias: next(line for item in chapters for line in item["dialogue"]["lines"] if str(line["line_id"]) == source) for source, alias in alias_by_line.items()}
    deps.begin_draft_llm_call(job_id, phase="notation", message="表記候補を抽出しています")
    system = "あなたは日本語台詞の局所表記監査者です。候補以外は判断も出力もしない。引用・反復・引用らしい節は変更しない。二人称代名詞へ基本の敬称を機械結合した候補は、指定された自然な二人称へ直す。修正できる場合だけ `L1|文字位置(0始まり)|期待する原文|置換後文字列` を一行で返す。行全体、説明、JSON、Markdownは禁止。"
    context = [{"line": alias, "speaker": cast_alias_by_id.get(str(line.get("character_id")), "?"), "text": str(line.get("text"))} for alias, line in line_sources.items()]
    def on_progress(streamed: str) -> None:
        deps.update_draft_job(
            job_id,
            receivedCharacters=len(streamed),
            receivedRecords=len(_parse_patches(streamed)),
            message="確認結果を受信しています",
        )
    contract, candidates_by_id = _notation_contract(candidates)
    response = deps.complete_records(
        request, contract=contract, system=system,
        user={"candidates": [{"alias": alias, **value}
                             for alias, value in candidates_by_id.items()], "minimum_context": context},
        max_tokens=min(1024, token_budget), temperature=0.1, stream=True,
        sampling_policy="deterministic", debug_response_path=debug_directory / "attempt-1.txt",
        on_progress=on_progress, should_cancel=should_cancel, job_id=job_id,
    )
    content = _project_notation(response.records, candidates_by_id)
    patches = _parse_patches(content)
    accepted, conflicts, _ = _validated_patches(chapters, candidates, patches, line_sources)
    if conflicts or not patches:
        retry_candidates = candidates if not patches else [candidate for candidate in candidates if (candidate["line"], candidate["offset"]) in {(item["line"], item["offset"]) for item in conflicts}]
        deps.update_draft_job(job_id, message="表記候補を抽出しています")
        retry_contract, retry_by_id = _notation_contract(retry_candidates)
        retry_response = deps.complete_records(
            request, contract=retry_contract, system=system,
            user={"candidates": [{"alias": alias, "kind": value.get("kind"), "choices": value.get("allowed")}
                                 for alias, value in retry_by_id.items()],
                  "accepted_patches_immutable": accepted, "minimum_context": context},
            max_tokens=min(1024, token_budget), temperature=0.1, stream=True,
            sampling_policy="deterministic", debug_response_path=debug_directory / "attempt-2.txt",
            on_progress=on_progress, should_cancel=should_cancel, job_id=job_id,
        )
        retry_content = _project_notation(retry_response.records, retry_by_id)
        retry_accepted, _, _ = _validated_patches(chapters, retry_candidates, _parse_patches(retry_content), line_sources)
        occupied = {(item["line"], item["offset"]) for item in accepted}
        accepted.extend(item for item in retry_accepted if (item["line"], item["offset"]) not in occupied)
    deps.update_draft_job(job_id, message="パッチを検証しています", notationCompletedSteps=2)
    deps.advance_draft_progress(
        job_id,
        overall_progress=deps.DRAFT_PROGRESS_DIALOGUE_END
        + (deps.DRAFT_PROGRESS_NOTATION_END - deps.DRAFT_PROGRESS_DIALOGUE_END) * 2 / 3,
    )
    accepted = _apply_patches(chapters, candidates, accepted, line_sources)
    deps.write_draft_debug_response(
        debug_directory / "notation-patches-result.json",
        json.dumps(
            {"received": patches, "applied": accepted, "rejected": len(patches) - len(accepted)},
            ensure_ascii=False,
            indent=2,
        ),
    )
    for item in chapters:
        item["spoken"] = deps.spoken_dialogue_count(item["dialogue"])
    deps.update_draft_job(job_id, message="パッチを検証しています", notationCompletedSteps=3)
    deps.advance_draft_progress(job_id, overall_progress=deps.DRAFT_PROGRESS_NOTATION_END)
    return chapters


def normalize_draft_notation_locally(drafted_chapters):
    """Apply only deterministic one-to-one glyph substitutions."""
    return _apply_safe_glyphs(drafted_chapters)


deps.register(__name__, ["normalize_draft_notation", "normalize_draft_notation_locally"])

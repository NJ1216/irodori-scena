from __future__ import annotations

from server.app_deps import re, Path, Any, Callable
from server.registry import deps


def _parse_repair_rows(content: str):
    rows: dict[str, tuple[str, str]] = {}
    additions: list[tuple[int, str, str]] = []
    for raw_row in content.splitlines():
        match = re.match("^(C(\\d{3})(L\\d{3})?)\\|([A-Z]+)\\|(.*)$", raw_row.strip())
        if not match:
            continue
        row_id, chapter_number, line_suffix, alias, text = match.groups()
        if line_suffix:
            rows[row_id] = (alias, text.strip())
        else:
            additions.append((int(chapter_number), alias, text.strip()))
    return rows, additions


def _apply_repair_additions(drafted_chapters, additions, cast_alias_by_id):
    candidate_chapters = []
    for item in drafted_chapters:
        dialogue = {
            **item["dialogue"],
            "lines": [dict(line) for line in item["dialogue"].get("lines", [])],
        }
        candidate_chapters.append({**item, "dialogue": dialogue})
    aliases_to_id = {alias: cast_id for cast_id, alias in cast_alias_by_id.items()}
    accepted = 0
    for chapter_number, alias, text in additions:
        cleaned = deps.strip_draft_emojis(text).strip()
        if not cleaned or alias not in aliases_to_id or not 1 <= chapter_number <= len(candidate_chapters):
            continue
        candidate_chapters[chapter_number - 1]["dialogue"]["lines"].append(
            {"character_id": aliases_to_id[alias], "text": cleaned}
        )
        accepted += 1
    for index, item in enumerate(candidate_chapters):
        deps.resequence_draft_dialogue(item["dialogue"], index)
        item["spoken"] = deps.spoken_dialogue_count(item["dialogue"])
    return candidate_chapters, accepted


def _repair_contract(chapter_count, cast_alias_by_id):
    chapters = [f"C{index:03d}" for index in range(1, chapter_count + 1)]
    speakers = sorted(set(cast_alias_by_id.values()))
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "chapter": {"type": "string", "enum": chapters},
        "speaker": {"type": "string", "enum": speakers}, "text": {"type": "string"},
    }, "required": ["chapter", "speaker", "text"]}
    def legacy(content):
        _, additions = _parse_repair_rows(content)
        return [{"chapter": f"C{chapter:03d}", "speaker": speaker, "text": text}
                for chapter, speaker, text in additions]
    return deps.LlmRecordContract(
        "draft-repair", 1, schema, "chapter", frozenset(chapters),
        legacy_suffix="追加行だけをC001|A|台詞本文の既定形式で返す。", legacy_parser=legacy,
        merge_by_owner=False,
    )


def repair_draft_dialogue(
    request: deps.DraftRequest,
    *,
    job_id: str,
    cast_context: list[dict[str, Any]],
    plan: dict[str, Any],
    drafted_chapters: list[dict[str, Any]],
    cast_alias_by_id: dict[str, str],
    priority_by_cast_id: dict[str, str],
    token_budget: int,
    debug_directory: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Repair only cast-priority or missing-cast violations.

    The normal path deliberately never invokes this function.  When a repair
    is needed, every source row is immutable; the model may only append rows
    needed to satisfy cast priority or participating-cast presence.
    """
    source_lines = [line for item in drafted_chapters for line in item["dialogue"].get("lines", [])]
    priority_valid = deps.draft_priority_is_satisfied({"lines": source_lines}, priority_by_cast_id)
    source_casts = {str(line.get("character_id", "")) for line in source_lines}
    missing_casts = set(priority_by_cast_id) - source_casts
    if priority_valid and (not missing_casts):
        return drafted_chapters
    deps.update_draft_job(job_id, draftFinishingStepRequired=True)
    priority_by_alias = {
        cast_alias_by_id.get(cast_id, cast_id): priority for cast_id, priority in priority_by_cast_id.items()
    }
    nearby_lines = [
        line for item in drafted_chapters for line in item["dialogue"].get("lines", [])[-3:]
    ]
    source_rows = "\n".join(
        f"{line['line_id']}|{cast_alias_by_id.get(str(line['character_id']), '?')}|{line['text']}"
        for line in nearby_lines
    )
    chapter_cast_totals = [
        {
            "chapter": index + 1,
            "spoken_characters_by_cast": {
                alias: sum(
                    len(str(line.get("text", "")))
                    for line in item["dialogue"].get("lines", [])
                    if str(line.get("character_id", "")) == cast_id
                )
                for cast_id, alias in cast_alias_by_id.items()
            },
        }
        for index, item in enumerate(drafted_chapters)
    ]
    issues: list[str] = []
    if not priority_valid:
        issues.append("main、supporting、standard の順に全体発話量を多くする")
    if missing_casts:
        issues.append("発話のない参加キャストを追加する")
    system = "あなたは日本語音声ドラマ台本の発話量制約修復者です。要約・圧縮・通常編集は禁止です。\nsource_rows は変更不可の参照情報です。キャスト優先度または未発話キャストを満たすために必要な新規行だけを追加してください。出来事、間、フィラー、内心表現を保持してください。relations.address を最優先し、二人称代名詞と基本の敬称を機械的に連結して「あなたさん」「君さん」のような呼称を作らないでください。Unicode絵文字を一切出力しないでください。\n追加行は追加先章を指定する `C001|A|台詞本文` とします。既存行、JSON、Markdown、説明、見出しは出力しないでください。"
    deps.begin_draft_llm_call(
        job_id,
        phase="repairing",
        message="台本の制約を修復しています（" + "、".join(issues) + "）…",
    )

    def report_repair_stream(streamed: str) -> None:
        deps.update_draft_job(
            job_id,
            receivedCharacters=len(streamed),
            receivedRecords=len(re.findall("^C\\d{3}\\|", streamed, re.MULTILINE)),
        )

    try:
        response = deps.complete_records(
            request,
            contract=_repair_contract(len(drafted_chapters), cast_alias_by_id),
            system=system,
            user={
                "participating_casts": cast_context,
                "cast_priority": priority_by_alias,
                "theme_or_situation": request.theme,
                "story_bible": plan.get("story_bible", ""),
                "global_chapter_outline": deps.compact_draft_chapter_outline(plan.get("chapters", [])),
                "chapter_cast_totals": chapter_cast_totals,
                "repair_issues": issues,
                "nearby_immutable_rows": source_rows,
                "output_format": "C001|A|appended row",
            },
            max_tokens=deps.dialogue_output_token_budget(
                max(700, deps.spoken_dialogue_count({"lines": source_lines})), token_budget
            ),
            stream=True,
            temperature=0.2,
            debug_response_path=debug_directory / "global-repair-attempt-1.txt",
            on_progress=report_repair_stream,
            loop_detector=deps.draft_dialogue_loop_reason,
            should_cancel=should_cancel,
            job_id=job_id,
        )
        content = "\n".join(f"{row['chapter']}|{row['speaker']}|{row['text']}" for row in response.records)
    except deps.DraftStreamLoopError as error:
        content = error.content
        deps.update_draft_job(job_id, loopDetected=str(error))
    _, additions = _parse_repair_rows(content)
    candidate_chapters, accepted = _apply_repair_additions(drafted_chapters, additions, cast_alias_by_id)
    if accepted:
        return candidate_chapters
    raise RuntimeError("台本の制約を修復できませんでした: 利用可能な追加行がありません。")


deps.register(__name__, ["repair_draft_dialogue"])

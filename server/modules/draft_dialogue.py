from __future__ import annotations

from server.app_deps import json, math, os, Path, Any, Callable
from server.registry import deps
from server.modules.draft_scoped_protocol import parse_scoped_dialogue
from server.modules.draft_call_fit import fit_dialogue_request
from server.modules.draft_text_rules import _strict_float
def _recent_dialogue_context(lines: list[dict[str, Any]], cast_alias_by_id: dict[str, str]) -> dict[str, Any]:
    """Keep accepted facts visible; fitting reduces new work before dropping history."""
    recent = lines
    return {
        "accepted_spoken_characters": deps.spoken_dialogue_count({"lines": lines}),
        "recent_complete_lines": deps.draft_dialogue_prompt_records(recent, cast_alias_by_id),
        "resent_recent_line_count": len(recent),
    }

def _schema_dialogue(records: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Convert independently validated schema records without losing ownership."""
    lines = []
    for record in records:
        speaker = str(record.get("speaker", "")).strip()
        text = str(record.get("text", "")).strip()
        source = str(record.get("source") or "").strip()
        if not speaker or not text:
            continue
        values = {key: record.get(key) for key in ("emoji", "rate", "gap", "direction", "cue")
                  if record.get(key) is not None}
        text, values = deps.recover_leaked_json_direction(text, values)
        if not text:
            continue
        line = {"character_id": speaker, "text": text, "development_id": source,
                "integrated_direction_attempted": True}
        if record.get("source_complete") is True:
            line["source_complete"] = True
        if values:
            line["integrated_direction"] = values
            line["integrated_direction_source_text"] = text
        lines.append(line)
    for index, line in enumerate(lines):
        line["integrated_direction_origin"] = f"R{index + 1}"
        line["integrated_direction_next_origin"] = f"R{index + 2}" if index + 1 < len(lines) else "END"
    return {"lines": lines, "_completed_sources": list(dict.fromkeys(
        row["source"] for row in records if row.get("source_complete") and row.get("source")))}
def _schema_stream_enabled(request: deps.DraftRequest) -> bool:
    if os.getenv("SCENA_DISABLE_STRUCTURED_OUTPUT", "").strip() == "1":
        return False
    if deps.ollama_structured_enabled(request):
        return True
    capabilities = deps.resolve_llm_capabilities(request.provider, request.base_url, request.model)
    structured = capabilities.get("structuredOutput") if isinstance(capabilities, dict) else None
    streaming = structured.get("streaming") if isinstance(structured, dict) else None
    return isinstance(streaming, dict) and streaming.get("state") in {"constrained", "schema_validated"}

def _emoji_schema_example(enabled_by_alias: dict[str, bool], allowed: set[str]) -> dict[str, Any]:
    lines = []
    enabled = next((alias for alias, value in enabled_by_alias.items() if value), None)
    disabled = next((alias for alias, value in enabled_by_alias.items() if not value), None)
    if enabled and allowed:
        lines.append({"speaker": enabled, "text": "今日は楽しみだね。",
                      "emoji": f"{next(iter(sorted(allowed)))}@楽しみ", "rate": "1.00", "gap": "0.70",
                      "direction": "明るく", "cue": "NORMAL"})
    if disabled:
        lines.append({"speaker": disabled, "text": "うん、行こう。", "emoji": None,
                      "rate": "1.00", "gap": "0.70", "direction": "穏やかに", "cue": "NORMAL"})
    if not lines:
        lines.append({"speaker": next(iter(enabled_by_alias), "A"), "text": "うん、行こう。", "emoji": None,
                      "rate": "1.00", "gap": "0.70", "direction": "穏やかに", "cue": "NORMAL"})
    return {"D1.1": {"lines": lines}}

def _as_packet_chapters(chapter: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    return chapter if isinstance(chapter, list) else [chapter]

def generate_draft_dialogue(
    request: deps.DraftRequest,
    *,
    cast_context: list[dict[str, Any]],
    plan: dict[str, Any],
    chapter: dict[str, Any] | list[dict[str, Any]],
    chapter_index: int,
    requested_characters: int,
    remaining_characters: int,
    accepted_dialogue: dict[str, Any],
    continuity_state: str,
    completion_ledger: dict[str, Any] | None = None,
    token_budget: int,
    cast_alias_by_id: dict[str, str],
    debug_response_path: Path | None = None,
    on_progress: Callable[[str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    job_id: str | None = None,
    benchmark_seed: int | None = None,
    source_targets: dict[str, int] | None = None,
) -> tuple[dict[str, Any], str | None]:
    _, filler_guidance = deps.draft_expression_guidance(request)
    existing_lines = accepted_dialogue.get("lines", [])
    average_line_length = (
        sum(len(str(line.get("text", ""))) for line in existing_lines) / len(existing_lines)
        if existing_lines else 45
    )
    recommended_line_count = max(1, math.ceil(requested_characters / max(1, average_line_length)))
    has_accepted = bool(accepted_dialogue.get("lines"))
    packet_chapters = _as_packet_chapters(chapter)
    development_ids = [str(item).split("|", 1)[0].strip()
                       for packet_chapter in packet_chapters for item in packet_chapter.get("beats", [])]
    development_ids = [item for item in development_ids if item]
    simultaneous_writing_rule = """
同時発話へ移る合図と、実際に複数人が同時に言う本文を一つの発話行へ混在させない。各行の先頭種別を本文を書く前に決める。合図・カウント・前置きは必ずNORMALの独立行にし、SIM行には最初の一文字から最後の一文字まで全員と同時に発話する本文だけを書く。たとえば一人が「せーの！やっほ〜！」と呼びかけ、もう一人が同時に別の「こんにちは！」を言う場面は、`NORMAL|A|せーの！`、`SIM:S1|A|やっほ〜！`、`SIM:S1|B|こんにちは！` の連続行へ分ける。同時発話メンバーの本文は互いに同じ文章である必要はない。途中の語句だけを同時発話にする制御記号は使わない。
""" if request.simultaneous_cues else ""
    emoji_enabled_by_alias = {
        alias: deps.emoji_enabled_for_cast(request, cast_id)
        for cast_id, alias in cast_alias_by_id.items()
    }
    cue_contract = (
        "明確な同時発話候補の連続2〜8行だけ、行頭種別へ完全に同じ `SIM:S1` 形式の値を書く。"
        "SAME_1、S1、H-SAME_1など別形式は禁止。通常行はNORMAL。章のbeatsやテーマが一斉反応、唱和、"
        "複数人が同時に話す実演を明示する場合は、少なくとも一組を実際の連続SIM行として作る。"
        if request.simultaneous_cues else "行頭種別は常にNORMAL。"
    )
    overlap_contract = (
        "割り込み、遮り、畳み掛け、前の発話が終わる前の被せが自然な箇所では、先行行のgapへ許容範囲内の負値を使う。"
        "たとえばBがAへ割り込む二行は、Aの行を`gap=-0.40`、Bの行を通常のgapにする。"
        "割り込むB自身へ負値を書くと、さらに次のCがBへ被さる逆の意味になるため禁止する。"
        "テーマやbeatsが被せ発話を明示する場合は、少なくとも一箇所で負のgapを使う。"
        if request.overlapping_speech else "gapへ負値を書かない。"
    )
    policy = deps.performance_direction_policy(request)
    allowed_ai_emojis = deps.ai_allowed_emojis(request, request.allowed_emojis)
    performance_rules = deps.performance_direction_prompt_rules(policy)
    cast_emoji_rules = (
        "各発話ではrequest_settings.emoji_enabled_by_castをspeakerごとに必ず適用する。"
        "trueのspeakerでは演技上適切な箇所へemojiを積極的に提案できるが、全行への付与はしない。"
        "falseのspeakerはemojiを必ずnullまたはNONEにする。"
    )
    output_record = (
        "`NORMAL|A|台詞本文||emoji=NONE|rate=1.00|gap=0.70|direction=穏やかに` または "
        "`SIM:S1|A|台詞本文||emoji=NONE|rate=1.00|gap=0.70|direction=明るく`"
        if request.simultaneous_cues else
        "`NORMAL|A|台詞本文||emoji=NONE|rate=1.00|gap=0.70|direction=穏やかに`"
    )
    record_prefix = "NORMALまたはSIM:S1形式" if request.simultaneous_cues else "NORMAL"
    common_system = """あなたは日本語の音声ドラマ脚本家・演出家です。全体台本の連続した章・展開について新しい台詞だけを書く。これは scena-integrated-draft-forward-v3 プロトコルである。
global_chapter_outlineとcurrent_packetを守り、未完了のbeatsを会話として前へ進める。会話の往復、具体例、相手の反応、迷い、判断、次の話題への変化を掘り下げ、同じフィラー・語句・句読点の反復で長さを作らない。一発話は約45文字を目安に、自然な一行として書く。
source_target_charactersとsource_recommended_line_countは展開IDごとの配分であり、総量を一場面で使わない。各場面の配分内で開始状態から終了状態までの具体的な内容を語り、その場面のlinesを閉じてから次のIDへ移る。target_new_spoken_charactersは全場面の合計目安で、最大量を超えて尺を延ばさない。予定行数の前半に具体的な出来事と異なる反応、中盤に疑問・試行・判断、最後にその場面の解決を配置し、解決後に行数を埋める反復を追加しない。
今回指定されていない後続場面の話題を先取りして詳しく語らない。特に導入では挨拶と見通しまでに留める。既に紹介した話題へ戻る場合も導入をやり直さず、未提示の具体的な出来事や判断へ進む。「これから詳しく話す」「準備はいい？」といった予告だけを重ねず、その場面で実際に内容を語る。
accepted_dialogue_so_far は既に確定している。内容を変更、要約、復唱、言い換えせず、最後の発話から自然に続く新規部分だけを返す。確定済み台詞を出力へ含めない。
final_conclusionがfalseの場面では物語や配信全体を終了しない。trueの最終場面だけで結末・配信の締めを成立させ、その後に新しい話題や展開を追加しない。
completion_ledger に載る完了済み展開は、既に物語上で成立し終えた事実である。再演、再導入、初発見としての扱い、別表現での繰り返しをせず、確定済みの最新状態の後から開始する。
「…」「!?」「ーっ」などはIrodori-TTSが発話する有効な本文なので、演技上必要ならそのまま使う。台詞本文にはUnicode絵文字を一切出力しない。許可された表情EMOJIだけをemojiフィールドへアンカー形式で提案する。
theme_or_situation と current_packet の舞台・出来事を最優先し、キャストの職業・背景から作者未指定の事件や世界観を追加しない。
participating_casts の profile、一人称・二人称・呼び方・relationsを守る。preferences.priority が main の各キャストは supporting より、supporting は standard より、章全体の発話量が多くなるよう配分する。キャスト名は name と完全一致させ、簡体字中国語を混ぜず自然な日本語で書く。
二人称代名詞と敬称は機械的に連結しない。relations.address があればその呼び方を最優先し、基本の敬称は人名または明示された呼称へだけ付ける。「あなたさん」「君さん」のような不自然な合成呼称は禁止する。
選別済みの任意設定も使用必須ではなく、自然な場合だけ短く言及できる参考情報である。テーマと現在の会話目的を最優先し、キャスト設定を順番に紹介したり台詞で自己申告させたりしない。無関係な趣味・好物・苦手・職業・過去を新しい話題や事件のきっかけにしない。設定を使わなくても人物像と矛盾しなければ正常であり、作者がテーマ文で明示した設定は題材として優先する。
""" + simultaneous_writing_rule + performance_rules + cast_emoji_rules
    schema_example = _emoji_schema_example(emoji_enabled_by_alias, allowed_ai_emojis)
    schema_system = common_system + """
出力はcurrent_packetに示された展開IDをキーとするJSON objectだけとする。全展開IDを計画順に一度ずつ必ず返し、各値はlines配列とcompleteを持つobjectとする。場面の終了状態が本文で実際に成立した場合だけcompleteをtrueにする。今回の出力量では途中までの場合はfalseにし、次の場面を始めない。各発話はspeaker、text、emoji、rate、gap、direction、cueを持つ。speakerは短いcast記号とする。展開を完了してから次の展開へ進む。textには発話本文だけを書き、`台詞本文」「emoji":"…」「rate":"…`のように兄弟プロパティを複写しない。
例: """ + json.dumps(schema_example, ensure_ascii=False, separators=(",", ":"))
    legacy_system = common_system + """
各展開を ::SOURCE|展開ID の行で開始し、書き終えたら ::SOURCE_END|同じ展開ID の行で閉じる。
指定された全展開を順番に書き、source_target_charactersの配分とtarget_new_spoken_charactersの総量を守る。
出力は一発話一行の """ + output_record + """ とする。行頭種別は本文を書く前に必ず""" + record_prefix + """で決定する。展開IDはSOURCEマーカーだけで示す。章番号は台詞へ書かない。本文に絵文字や@アンカーを書かず、emojiフィールドだけへ書く。gapは""" + overlap_contract + """行頭種別は""" + cue_contract + """SOURCEマーカー以外のJSON、Markdown、見出し、説明は禁止。
例: NORMAL|A|今日はどうしたの？||emoji=NONE|rate=1.00|gap=0.70|direction=気遣うように"""
    system = schema_system if _schema_stream_enabled(request) else legacy_system
    user = {"sections": [
        {"theme_or_situation": request.theme},
        {"request_settings": {
            "protocol_version": "scena-integrated-draft-forward-v3",
            "performance_ranges": {
                "speech_rate": [request.performance_speech_rate_min, request.performance_speech_rate_max],
                "gap_seconds": [request.performance_gap_min, request.performance_gap_max],
                "negative_gap_allowed": request.overlapping_speech,
            },
            "allowed_emojis": sorted(allowed_ai_emojis) if deps.emoji_enabled_for_request(request) else [],
            "emoji_enabled_by_cast": emoji_enabled_by_alias,
            "simultaneous_cues_enabled": request.simultaneous_cues,
            "filler_guidance": filler_guidance,
        }},
        {"participating_casts": cast_context},
        {"story_bible_and_global_outline": {
            "story_bible": plan.get("story_bible", ""),
            "global_chapter_outline": deps.compact_draft_chapter_outline(plan.get("chapters", [])),
        }},
        {"current_packet": packet_chapters},
        {"previous_chapter_state": continuity_state or "（最初の章。前章はない）"},
        {"completion_ledger": completion_ledger or {
            "completed_sources": [], "completed_chapters": [], "confirmed_closing_states": [],
        }},
        {"accepted_dialogue_and_current_request": {
            "minimum_new_spoken_characters": min(remaining_characters, requested_characters),
            "target_new_spoken_characters": requested_characters,
            "source_target_characters": source_targets or {},
            "recommended_new_line_count": recommended_line_count,
            "accepted_dialogue_so_far": _recent_dialogue_context(
                accepted_dialogue.get("lines", []), cast_alias_by_id
            ) if has_accepted else "（まだない）",
        }},
    ]}
    development_ids, requested_characters, output_tokens = fit_dialogue_request(
        request, system, user, requested_characters, token_budget)
    loop_reason: str | None = None
    streamed_prefix = ""
    allowed_speakers = set(cast_alias_by_id.values()) | set(cast_alias_by_id)
    speaker_aliases = {alias: alias for alias in cast_alias_by_id.values()}
    speaker_aliases.update(cast_alias_by_id)
    cast_names = [str(item.get("name", "")).strip() for item in cast_context]
    for cast in cast_context:
        name, alias = str(cast.get("name", "")).strip(), str(cast.get("cast", "")).strip()
        if name and alias and cast_names.count(name) == 1:
            allowed_speakers.add(name)
            speaker_aliases[name] = alias

    def legacy_dialogue(content):
        parsed = parse_scoped_dialogue(content, allowed_speakers=allowed_speakers, speaker_aliases=speaker_aliases)
        records = []
        for line in parsed.get("lines", []):
            values = line.get("integrated_direction") or {}
            records.append({"speaker": line["character_id"], "text": line["text"],
                            "emoji": values.get("emoji"), "rate": values.get("rate"),
                            "gap": values.get("gap"), "direction": values.get("direction"),
                            "cue": values.get("cue"), "source": line.get("development_id") or next(iter(development_ids), ""),
                            "source_complete": line.get("source_complete", False)})
        return records

    nullable = {"type": ["string", "null"]}
    line_schema = {
        "type": "object", "additionalProperties": False, "properties": {
            "speaker": {"type": "string", "enum": sorted(set(cast_alias_by_id.values()))},
            "text": {"type": "string"}, "emoji": nullable, "rate": nullable, "gap": nullable,
            "direction": nullable, "cue": nullable,
        }, "required": ["speaker", "text", "emoji", "rate", "gap", "direction", "cue"],
    }
    validation_schema = {**line_schema, "properties": {
        **line_schema["properties"], "source": {"type": "string", "enum": development_ids},
        "source_complete": {"type": "boolean"},
    }}
    contract = deps.LlmRecordContract("draft-dialogue", 2, validation_schema,
        "source", frozenset(development_ids), legacy_suffix="既定の一発話一行形式で返す。",
        legacy_parser=legacy_dialogue, merge_by_owner=False,
        loop_projection=lambda records: "\n".join(f"{row['speaker']}|{row['text']}" for row in records if row.get('speaker') and row.get('text')),
        response_schema_override=deps.required_source_schema(development_ids, line_schema),
        record_extractor=lambda content: deps.extract_required_sources(content, development_ids))

    def retain_progress(content: str) -> None:
        nonlocal streamed_prefix
        streamed_prefix = content
        if on_progress:
            on_progress(content)

    streamed_records = []
    def retain_records(records):
        streamed_records.extend(records)
        retain_progress("\n".join(
            f"{row.get('cue') or 'NORMAL'}|{row['speaker']}|{row['text']}||" + "|".join(
                f"{key}={row[key]}" for key in ("emoji", "rate", "gap", "direction") if row.get(key) is not None
            ) for row in streamed_records if row.get("speaker") and row.get("text")
        ))

    try:
        response = deps.complete_records(
            request,
            contract=contract,
            system=system,
            user=user,
            max_tokens=output_tokens,
            stream=True,
            temperature=0.8,
            debug_response_path=debug_response_path,
            on_records=retain_records,
            on_progress=retain_progress,
            should_cancel=should_cancel,
            job_id=job_id,
            benchmark_seed=benchmark_seed,
            loop_detector=deps.draft_dialogue_loop_reason,
        )
        content = "\n".join(
            f"{row.get('cue') or 'NORMAL'}|{row['speaker']}|{row['text']}||" + "|".join(
                f"{key}={row[key]}" for key in ("emoji", "rate", "gap", "direction") if row.get(key) is not None
            ) for row in response.records if row.get("speaker") and row.get("text")
        )
        parsed = _schema_dialogue(response.records)
        parsed["_contract_mode"] = response.mode
        parsed["_partial"] = bool(response.transport.partial)
        parsed["_manifest"] = list(response.manifest)
        parsed["_finish_reason"] = response.transport.finish_reason
        parsed["_provider_output_tokens"] = response.transport.usage.get("completionTokens")
    except deps.DraftStreamLoopError as error:
        content = error.content
        loop_reason = str(error)
    except deps.GenerationCancelled:
        raise
    except Exception as error:
        if not streamed_prefix:
            raise
        content = streamed_prefix
        loop_reason = f"stream interrupted: {type(error).__name__}"
    if "parsed" not in locals():
        parsed = _schema_dialogue(tuple(streamed_records or legacy_dialogue(content)))
        parsed["_contract_mode"] = "schema" if streamed_records else "legacy"
        parsed["_partial"] = bool(loop_reason)
        parsed["_manifest"] = []
    parsed["_requested_sources"] = development_ids
    parsed["_requested_characters"] = requested_characters
    cast_id_by_alias = {alias: cast_id for cast_id, alias in cast_alias_by_id.items()}
    valid_fields = sum(
        deps.usable_integrated_field_count(
            request,
            {**line, "character_id": cast_id_by_alias.get(str(line.get("character_id", "")), "")},
        )
        for line in parsed.get("lines", [])
    )
    if job_id:
        with deps.DRAFT_JOBS_LOCK:
            job = deps.DRAFT_JOBS.get(job_id)
            if isinstance(job, dict) and "integratedDirectionMode" not in job:
                job["integratedDirectionMode"] = "integrated" if valid_fields else "legacy"
                job["integratedDirectionFallbackReason"] = (
                    "" if valid_fields else "first response contained no direction fields"
                )
    return parsed, loop_reason

def normalize_draft_dialogue(
    raw: dict[str, Any],
    *,
    permitted: set[str],
    character_name_to_id: dict[str, str],
    chapter_index: int,
    line_offset: int = 0,
) -> dict[str, Any]:
    """Validate speaker IDs and establish globally unique immutable line IDs."""
    lines: list[dict[str, Any]] = []
    for number, raw_line in enumerate(raw.get("lines", []), start=1):
        if not isinstance(raw_line, dict):
            continue
        character_id = str(raw_line.get("character_id", "")).strip()
        character_id = character_name_to_id.get(character_id, character_id)
        text = deps.strip_draft_emojis(str(raw_line.get("text", ""))).strip()
        if character_id not in permitted or not text:
            continue
        normalized = {
                "line_id": f"C{chapter_index + 1:03d}L{line_offset + number:03d}",
                "character_id": character_id,
            "text": text,
        }
        if str(raw_line.get("development_id", "")).strip():
            normalized["development_id"] = str(raw_line["development_id"]).strip()
        if raw_line.get("source_complete") is True:
            normalized["source_complete"] = True
        values = raw_line.get("integrated_direction")
        if isinstance(values, dict) and values:
            normalized["integrated_direction"] = dict(values)
            normalized["integrated_direction_source_text"] = str(
                raw_line.get("integrated_direction_source_text", text)
            )
        if raw_line.get("integrated_direction_attempted") is True:
            normalized["integrated_direction_attempted"] = True
            normalized["integrated_direction_origin"] = str(raw_line.get("integrated_direction_origin", ""))
            normalized["integrated_direction_next_origin"] = str(raw_line.get("integrated_direction_next_origin", ""))
        lines.append(normalized)
    return {"title": str(raw.get("title", "Scene")).strip() or "Scene", "lines": lines}

def assemble_draft_performance(
    dialogue: dict[str, Any], parsed: dict[str, Any], *, lookahead_lines: list[dict[str, Any]],
    speech_rate_min: float = deps.LINE_SPEECH_RATE_MIN,
    speech_rate_max: float = deps.LINE_SPEECH_RATE_MAX,
    gap_min: float = 0,
    gap_max: float = 9999,
    allowed_emojis: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str], int]:
    """Accept explicit LLM acting decisions and deterministically apply draft constraints."""
    performances = parsed.get("performances", {})
    transitions = parsed.get("transitions", {})
    constrained = allowed_emojis is not None
    lines = dialogue.get("lines", [])
    accepted: list[dict[str, Any]] = []
    invalid_lines: list[str] = []
    invalid_transitions: list[str] = []
    text_corrections = 0
    for index, line in enumerate(lines):
        line_id = str(line.get("line_id", ""))
        performance = performances.get(line_id, {}) if isinstance(performances, dict) else {}
        performed_text = str(performance.get("performed_text", "")).strip()
        source_text = str(line.get("text", ""))
        emoji_free_performed_text = deps.strip_draft_emojis(performed_text)
        text_matches = emoji_free_performed_text == source_text
        text_fallback = bool(performed_text) and not text_matches
        direction = deps.strip_draft_emojis(str(performance.get("stage_direction", ""))).strip()
        speech_rate = _strict_float(performance.get("speech_rate"))
        performance_valid = not (
            not performed_text
            or not direction
            or speech_rate is None
            or (not constrained and not deps.LINE_SPEECH_RATE_MIN <= speech_rate <= deps.LINE_SPEECH_RATE_MAX)
        )
        if not performance_valid:
            invalid_lines.append(line_id)
        if index + 1 < len(lines):
            next_id = str(lines[index + 1].get("line_id", ""))
        elif lookahead_lines:
            next_id = str(lookahead_lines[0].get("line_id", ""))
        else:
            next_id = "END"
        edge = f"{line_id}->{next_id}"
        transition = transitions.get(edge, {}) if isinstance(transitions, dict) else {}
        gap = _strict_float(transition.get("gap_seconds"))
        transition_valid = gap is not None and (constrained or 0 <= gap <= 9999)
        if not transition_valid:
            invalid_transitions.append(edge)
        if not performance_valid or not transition_valid:
            continue
        assert speech_rate is not None and gap is not None
        final_text = source_text if text_fallback else deps.retain_supported_draft_emojis(
            performed_text, allowed=allowed_emojis
        )
        final_text = deps.enforce_tutting_intent(final_text, direction)
        accepted.append(
            {
                "id": deps.new_id("line"),
                "characterId": str(line.get("character_id", "")),
                "text": final_text,
                "stageDirection": direction,
                "speechRate": round(max(speech_rate_min, min(speech_rate_max, speech_rate)), 2),
                "gapSeconds": round(max(gap_min, min(gap_max, gap)), 2),
                "takes": [],
                "selectedTakeId": None,
            }
        )
    return (accepted, invalid_lines, invalid_transitions, text_corrections)

deps.register(
    __name__,
    [
        "assemble_draft_performance",
        "generate_draft_dialogue",
        "normalize_draft_dialogue",
    ],
)

from __future__ import annotations

from server.app_deps import Any, HTTPException
from server.registry import deps
from server.modules.voice_design import VOICE_DESIGN_OPTIONS
from server.modules.llm_voice_design_parser import (
    collapse_adjacent_voice_design_sentences as collapse_adjacent_voice_design_sentences,
    is_japanese_voice_design_caption,
    is_voice_design_emoji_tail_character as is_voice_design_emoji_tail_character,
    strip_trailing_voice_design_emojis as strip_trailing_voice_design_emojis,
)


def theme_suggestion_guidance(target_minutes: float, source_length: int) -> tuple[str, str, int]:
    """Return duration-scaled length, structure, and a context-safe output budget."""
    lower, upper = deps.draft_theme_length_bounds(target_minutes)
    if target_minutes <= 3:
        structure = "一つの状況、きっかけ、小さな変化、着地点に絞り、複雑な背景や副筋は入れません。"
    elif target_minutes <= 10:
        structure = "中心となる出来事、数段階の進展、一度の転換、明確な着地点を用意します。"
    elif target_minutes <= 20:
        structure = "導入・展開・転換・結末と、人物の目的や感情変化を具体化します。"
    elif target_minutes <= 40:
        structure = "複数の展開、伏線、対立の深まり、クライマックスまでの因果関係を設計します。"
    else:
        structure = "複数幕相当の進行、各人物の変化、伏線と回収、クライマックス、余韻まで詳細に設計します。"
    output_characters = min(4000, max(upper, source_length + 200))
    max_tokens = min(4096, round(output_characters * 1.5) + 256)
    return f"{lower}〜{upper}文字", structure, max_tokens


def suggest_theme_completion(request: deps.ThemeSuggestionRequest, *, benchmark_seed: int | None = None) -> str:
    project = deps.read_project()
    selected_ids = set(request.character_ids)
    available_ids = {str(character.get("id", "")) for character in project.get("characters", [])}
    if not selected_ids.issubset(available_ids):
        raise HTTPException(status_code=422, detail="選択したキャストが見つかりません。")
    selected_characters = [
        character for character in project.get("characters", []) if str(character.get("id", "")) in selected_ids
    ]
    aliases = deps.draft_cast_aliases(selected_characters)
    cast_context, _cast_audit = deps.compile_cast_context(
        request,
        selected_characters,
        project_id=str(project.get("id", "default")),
        aliases=aliases,
    )
    for item, character in zip(cast_context, selected_characters):
        settings = request.cast_settings.get(str(character.get("id", "")), deps.DraftCastSettings())
        item["draft_settings"] = {
            "emoji_expressions": settings.emoji_expressions,
            "filler_richness": settings.filler_richness,
            "appearance_priority": settings.appearance_priority,
        }
    source_theme = request.theme.strip()
    proposal_mode = "入力テキストを軸に詳細化" if source_theme else "キャストに合う新規案"
    length_target, structure_guidance, max_tokens = theme_suggestion_guidance(request.target_minutes, len(source_theme))
    system = f"あなたは日本語の音声台本の企画編集者です。約{request.target_minutes:g}分の台本生成へそのまま渡せる、具体的な企画本文を読みやすい日本語の段落で書いてください。{length_target}を品質目標に、舞台、発端、出来事の進行、対立や転換、着地点が分かるようにします。{structure_guidance}長尺でも台詞本文は書かず、台詞やUnicode絵文字を含めません。見出し、`項目: 内容`、箇条書き、JSON、Markdownは使わず、企画本文だけを返してください。\n作者の入力がある場合は、固有名詞、人数、場所・時代、関係性、出来事の順序、制約、否定条件、目的、結末をすべて残し、尺に対して情報が多くても抽象化・要約・削除をしてはいけません。足りない具体性とドラマの進行だけを補います。作者が明示していないエコー・リバーブ・残響などの音響効果を追加しません。入力が空の場合も音響効果を考案せず、選択キャストに自然に合う新しい舞台と出来事を自由に考案します。\n選択キャストの情報は発想と整合性のための内部資料です。キャスト名一覧、プロフィール要約、関係設定、EMOJI・フィラー・登場優先度など、台本生成時に別途渡される情報を企画本文へ列挙・反復しないでください。"
    user = {
        "proposal_mode": proposal_mode,
        "target_minutes": request.target_minutes,
        "source_theme": source_theme or "（指定なし。選択キャストに合う新規案を作る）",
        "selected_cast": cast_context,
        "editing_rule": (
            "既入力の具体条件を一つも削らず、出来事の因果と推移を具体化する。"
            if source_theme
            else "キャスト情報を本文に列挙せず、新規の舞台、発端、進行、転換、着地点を考案する。"
        ),
        "output_requirement": f"見出しや箇条書きのない読みやすい複数段落。{length_target}を品質目標とする。",
    }
    debug_directory = deps.draft_debug_directory(f"theme-suggestion-{deps.new_id('request')}")

    try:
        raw = deps.complete_text(
            request,
            contract=deps.TEXT_CONTRACTS["theme-suggestion"],
            system=system,
            user=user,
            max_tokens=max_tokens,
            temperature=0.35 if source_theme else 0.8,
            debug_response_path=debug_directory / "attempt-1.txt",
            feature="theme-suggestion",
            benchmark_seed=benchmark_seed,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=f"テーマ提案のLLM呼び出しに失敗しました: {error}") from error
    normalized = deps.normalize_suggested_theme(raw)
    if normalized and len("".join(normalized.split())) >= 5:
        return normalized
    if normalized:
        raise HTTPException(
            status_code=502,
            detail="テーマ提案が短すぎて、台本生成へ渡せる具体的な企画本文になっていません。",
        )
    raise HTTPException(
        status_code=502,
        detail="テーマ提案の応答が空でした。LLMが企画本文を返しているか確認してください。",
    )


def _voice_design_contract(fields: set[str]):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "field": {"type": "string", "enum": sorted(fields)},
            "value": {"type": "string"},
        },
        "required": ["field", "value"],
    }

    def legacy(content):
        return [
            {"field": key, "value": value}
            for key, value in (deps.parse_voice_design(content) or {}).items()
            if key in fields
        ]

    return deps.LlmRecordContract(
        "voice-design",
        1,
        schema,
        "field",
        frozenset(fields),
        legacy_suffix="各項目を FIELD|内容 の1行形式で返し、JSON・Markdown・説明は出力しない。",
        legacy_parser=legacy,
    )


def suggest_voice_design_completion(request: deps.VoiceDesignSuggestionRequest) -> dict[str, Any]:
    allowed_emojis = deps.ai_allowed_emojis(request, deps.AI_PROPOSABLE_EMOJIS)
    emoji_catalog = "、".join(
        (
            f"{emoji}={label}（{description}）"
            for emoji, label, description in deps.AI_PROPOSABLE_EMOJI_CATALOG
            if emoji in allowed_emojis
        )
    )
    system = f"あなたは日本語音声の設計者です。AGE、GENDER、PITCH、QUALITY、STYLEは提示された固定選択肢から返します。QUALITYは読点区切りで複数選択できます。NOTESは選択肢にない補足だけを短く返します。BASELINE_TEXTは声質を聞き分けやすい約60文字の日本語の試聴台詞にします。NORMAL_TEXT、JOY_TEXT、ANGER_TEXT、SORROW_TEXT、DELIGHT_TEXTは各々短い一〜二文の日本語です。NORMAL_TEXTにはEMOJIを入れません。他の感情台詞には使えるEMOJIだけを発話途中へ入れます: {emoji_catalog}。タグ、括弧書き、舞台指示、引用符は使いません。各項目は一度だけ提案します。\n固定選択肢: {VOICE_DESIGN_OPTIONS}\n{deps.EMOJI_PERFORMANCE_RULEBOOK}"
    user = {
        "source_keywords": request.keywords.strip(),
        "character_context": request.character_context.strip(),
    }
    debug_directory = deps.draft_debug_directory(f"voice-design-suggestion-{deps.new_id('request')}")
    required_keys = {
        "AGE",
        "GENDER",
        "PITCH",
        "QUALITY",
        "STYLE",
        "NOTES",
        "BASELINE_TEXT",
        "NORMAL_TEXT",
        "JOY_TEXT",
        "ANGER_TEXT",
        "SORROW_TEXT",
        "DELIGHT_TEXT",
    }
    try:
        response = deps.complete_records(
            request,
            contract=_voice_design_contract(required_keys),
            system=system,
            user=user,
            max_tokens=1200,
            temperature=0.7,
            debug_response_path=debug_directory / "attempt-1.txt",
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    parsed = {row["field"]: row["value"] for row in response.records}
    if not parsed:
        raise HTTPException(status_code=502, detail="The LLM did not return usable voice-design suggestions.")
    design: dict[str, Any] = {}
    for field, target in (("AGE", "age"), ("GENDER", "gender"), ("PITCH", "pitch"), ("STYLE", "style")):
        value = parsed.get(field, "").strip()
        if value in VOICE_DESIGN_OPTIONS[field]:
            design[target] = value
    qualities = [item.strip() for item in parsed.get("QUALITY", "").replace("、", ",").split(",")]
    valid_qualities = [item for item in qualities if item in VOICE_DESIGN_OPTIONS["QUALITY"]]
    if valid_qualities:
        design["qualities"] = list(dict.fromkeys(valid_qualities))
    notes = deps.strip_draft_emojis(parsed.get("NOTES", "")).strip()
    if notes and len(notes) <= 600 and is_japanese_voice_design_caption(notes):
        design["notes"] = notes
    texts: dict[str, str] = {}
    for key, value in parsed.items():
        if key in {"AGE", "GENDER", "PITCH", "QUALITY", "STYLE", "NOTES"}:
            continue
        cleaned = deps.clean_voice_design_text(key, value, allowed=allowed_emojis)
        if 5 <= len(cleaned) <= 240 and is_japanese_voice_design_caption(cleaned):
            texts[key] = cleaned
    if not design and not texts:
        raise HTTPException(status_code=502, detail="LLMから日本語のVoice Design提案を受け取れませんでした。")
    emotion_keys = {
        "NORMAL_TEXT": "normal",
        "JOY_TEXT": "joy",
        "ANGER_TEXT": "anger",
        "SORROW_TEXT": "sorrow",
        "DELIGHT_TEXT": "delight",
    }
    return {
        "voiceDesign": design or None,
        "baselineText": texts.get("BASELINE_TEXT"),
        "emotionTexts": {emotion_keys[key]: value for key, value in texts.items() if key in emotion_keys},
    }


def _legacy_complete_missing_profile_targets(
    request,
    *,
    system,
    user,
    debug_directory,
    labels,
    blank_fields,
    other_casts,
    relation_aliases,
    proposed,
    relation_by_name,
):
    blank_relation_fields = {
        item["name"]: set(item["missing_relation_fields"]) for item in other_casts if item["missing_relation_fields"]
    }
    missing_fields = set(blank_fields) - set(proposed)
    accepted_relation_fields: dict[str, set[str]] = {}
    for name, fields in relation_by_name.items():
        accepted_relation_fields.setdefault(relation_aliases.get(name, name), set()).update(fields)
    missing_relations = {
        name: fields - accepted_relation_fields.get(name, set())
        for name, fields in blank_relation_fields.items()
        if fields - accepted_relation_fields.get(name, set())
    }
    if not missing_fields and not missing_relations:
        return proposed, relation_by_name
    retry_user = {
        **user,
        "accepted_settings_immutable": proposed,
        "accepted_relations_immutable": relation_by_name,
        "missing_fields": {field: labels[field] for field in missing_fields},
        "missing_relation_targets": {name: sorted(fields) for name, fields in missing_relations.items()},
        "format_correction": "不足対象だけをFIELD/RELATION行で返し、採用済み内容は変更・再出力しない。",
    }
    retry_content = deps.complete_text(
        request,
        contract=deps.TEXT_CONTRACTS["cast-relations"],
        system=system,
        user=retry_user,
        max_tokens=1600,
        temperature=0.55,
        debug_response_path=debug_directory / "attempt-2.txt",
    )
    retry_parsed = deps.parse_profile_suggestion(
        retry_content,
        labels=labels,
        blank_fields=missing_fields,
        allowed_relation_names=set(missing_relations)
        | {alias for alias, canonical in relation_aliases.items() if canonical in missing_relations},
        subject_name=request.name.strip(),
        allowed_relation_fields={
            **missing_relations,
            **{
                alias: missing_relations[canonical]
                for alias, canonical in relation_aliases.items()
                if canonical in missing_relations
            },
        },
    )
    if retry_parsed:
        retry_details, retry_relations = retry_parsed
        proposed.update({key: value for key, value in retry_details.items() if key not in proposed})
        for name, fields in retry_relations.items():
            current = relation_by_name.setdefault(name, {})
            current.update({key: value for key, value in fields.items() if key not in current})
    return proposed, relation_by_name


def _legacy_suggest_character_profile_completion(request: deps.CharacterProfileSuggestionRequest) -> dict[str, Any]:
    """Suggest only blank character-sheet values from the author's own clues."""
    details = deps.normalize_character_profile_details(request.profile_details)
    fields = [
        "familyName",
        "familyNameKana",
        "givenName",
        "givenNameKana",
        "aliases",
        "age",
        "bloodType",
        "birthDate",
        "birthplace",
        "residence",
        "gender",
        "role",
        "firstPerson",
        "secondPerson",
        "defaultAddressBasis",
        "defaultHonorific",
        "defaultAddressNote",
        "skills",
        "hobbies",
        "likes",
        "dislikes",
        "personality",
        "speechStyle",
        "background",
        "otherRelationships",
    ]
    blank_fields = [field for field in fields if not details.get(field)]
    existing_relations = details.get("castRelations", {})
    if not isinstance(existing_relations, dict):
        existing_relations = {}
    other_casts = []
    relation_alias_targets: dict[str, set[str]] = {}
    for cast in request.other_casts:
        cast_id = str(cast.get("id", "")).strip()[:120]
        cast_name = str(cast.get("name", "")).strip()[:80]
        if not cast_id or not cast_name:
            continue
        relation = existing_relations.get(cast_id, {})
        relation = relation if isinstance(relation, dict) else {"relationship": relation}
        address = str(relation.get("address", "")).strip()
        relationship = str(relation.get("relationship", relation.get("note", ""))).strip()
        profile_details = deps.normalize_character_profile_details(cast.get("profile_details"))
        missing_relation_fields = [
            field for field, value in (("address", address), ("relationship", relationship)) if not value
        ]
        if missing_relation_fields:
            family_name = str(profile_details.get("familyName", "")).strip()
            given_name = str(profile_details.get("givenName", "")).strip()
            if family_name and given_name:
                full_name = f"{family_name} {given_name}"
                relation_alias_targets.setdefault(full_name, set()).add(cast_id)
        other_casts.append(
            {
                "id": cast_id,
                "name": cast_name,
                "relationship_reference": deps.character_relation_reference(
                    {
                        "profile": str(cast.get("profile", "")).strip()[:2000],
                        "profileDetails": profile_details,
                    }
                ),
                "missing_relation_fields": missing_relation_fields,
                "existing_relation": {"address": address[:160], "relationship": relationship[:300]},
            }
        )
    relation_name_aliases = {
        alias: next(iter(cast_ids)) for alias, cast_ids in relation_alias_targets.items() if len(cast_ids) == 1
    }
    relation_names_by_id = {item["id"]: item["name"] for item in other_casts}
    relation_aliases = {
        alias: relation_names_by_id[cast_id]
        for alias, cast_id in relation_name_aliases.items()
        if cast_id in relation_names_by_id
    }
    labels = {
        "familyName": "苗字",
        "familyNameKana": "苗字のふりがな",
        "givenName": "名前",
        "givenNameKana": "名前のふりがな",
        "aliases": "愛称",
        "age": "年齢",
        "bloodType": "血液型",
        "birthDate": "誕生日",
        "birthplace": "出身地",
        "residence": "居住地",
        "gender": "性別",
        "role": "職業",
        "firstPerson": "一人称",
        "secondPerson": "二人称",
        "defaultAddressBasis": "呼び方の基準",
        "defaultHonorific": "基本の敬称",
        "defaultAddressNote": "呼び方の補足",
        "skills": "特技",
        "hobbies": "趣味",
        "likes": "好きなもの",
        "dislikes": "苦手なもの",
        "personality": "性格",
        "speechStyle": "基本の口調",
        "background": "背景・来歴",
        "otherRelationships": "その他の人間関係",
    }
    existing = {
        labels[field]: "／".join(value) if isinstance(value, list) else value
        for field, value in details.items()
        if field in labels and value
    }
    system = "あなたは日本語の創作キャラクター設定を作る編集者です。作者が決めた設定を最優先し、未設定項目だけを具体的な創作上の提案で埋める。入力済み項目は出力しない。作者が明示的に保留・禁止した場合を除き、情報が与えられていないことを理由に空欄を残してはいけない。`未設定`、`不明`、`なし`、`N/A`、仮置き表現は禁止し、各FIELDには作品内で使える固有の値を必ず入れる。作者のアイディア、自由メモ、既存キャストとの関係に矛盾しないよう一人の人物として整合させる。他キャストの情報はRELATIONを考えるための参照専用であり、氏名、年齢、属性、経歴、口調、趣味などを対象キャラクターのFIELDへ流用・複写してはいけない。誕生日は「4月18日」、ふりがなはひらがな。配列項目は値を `／` で区切る。RELATIONはこのキャラクターから見た相手への方向付き設定で、呼び方は実際の呼称とし、二人称代名詞と敬称を機械的に結合しない。「あなたさん」「君さん」や敬称を重ねた呼称は禁止する。「あなた様」「お前さん」は文脈に合えば使用できる。関係性は出会い・経緯・現在の距離・感情・隠した意図・会話時の態度を具体的に書く。相手の職業・年齢・プロフィールの要約だけを関係性にしてはいけない。未設定のサブ項目だけを `RELATION|キャスト名|呼び方|値` または `RELATION|キャスト名|関係性|値` で出力する。出力は `FIELD|表示名|値` と RELATION の行だけ。JSON、Markdown、説明は禁止。"
    user = {
        "character_name": request.name,
        "existing_settings": existing,
        "existing_free_memo": request.profile.strip() or "（未設定）",
        "author_idea": request.idea.strip() or "（追加アイディアなし）",
        "fillable_fields": {field: labels[field] for field in blank_fields},
        "other_casts": other_casts,
        "completion_rule": "fillable_fields の各項目は、作者が保留・禁止した場合を除き、未確定値ではなく具体的な創作提案で埋める。",
    }
    debug_directory = deps.draft_debug_directory(f"character-profile-suggestion-{deps.new_id('request')}")
    try:
        response_content = deps.complete_text(
            request,
            contract=deps.TEXT_CONTRACTS["character-profile"],
            system=system,
            user=user,
            max_tokens=1600,
            temperature=0.55,
            debug_response_path=debug_directory / "attempt-1.txt",
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    parsed = deps.parse_profile_suggestion(
        response_content,
        labels=labels,
        blank_fields=set(blank_fields),
        allowed_relation_names={item["name"] for item in other_casts if item["missing_relation_fields"]}
        | set(relation_aliases),
        subject_name=request.name.strip(),
        allowed_relation_fields={
            **{item["name"]: set(item["missing_relation_fields"]) for item in other_casts},
            **{
                alias: set(next(item["missing_relation_fields"] for item in other_casts if item["name"] == canonical))
                for alias, canonical in relation_aliases.items()
            },
        },
    )
    if not parsed:
        proposed, relation_by_name = {}, {}
    else:
        proposed, relation_by_name = parsed
    try:
        proposed, relation_by_name = _legacy_complete_missing_profile_targets(
            request,
            system=system,
            user=user,
            debug_directory=debug_directory,
            labels=labels,
            blank_fields=blank_fields,
            other_casts=other_casts,
            relation_aliases=relation_aliases,
            proposed=proposed,
            relation_by_name=relation_by_name,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if not proposed and not relation_by_name:
        raise HTTPException(status_code=502, detail="LLMから利用できるキャスト設定の提案を受け取れませんでした。")
    suggested_details = deps.normalize_character_profile_details(proposed)
    if relation_by_name:
        canonical_relation_by_name: dict[str, dict[str, str]] = {}
        for relation_name, fields in relation_by_name.items():
            canonical = relation_aliases.get(relation_name, relation_name)
            target = canonical_relation_by_name.setdefault(canonical, {})
            target.update({field: value for field, value in fields.items() if field not in target})
        allowed_relation_ids = {item["id"] for item in other_casts if item["missing_relation_fields"]}
        relation_suggestions: dict[str, Any] = {}
        for raw_relation_id, value in canonical_relation_by_name.items():
            relation_id = deps.resolve_suggested_relation_id(
                raw_relation_id, allowed_ids=allowed_relation_ids, other_casts=other_casts
            )
            if relation_id:
                relation_suggestions[relation_id] = value
        normalized_relations = deps.normalize_character_profile_details({"castRelations": relation_suggestions}).get(
            "castRelations"
        )
        if normalized_relations:
            suggested_details["castRelations"] = normalized_relations
    return {"profileDetails": suggested_details}


suggest_character_profile_completion = _legacy_suggest_character_profile_completion
deps.register(
    __name__,
    [
        "_legacy_suggest_character_profile_completion",
        "collapse_adjacent_voice_design_sentences",
        "is_japanese_voice_design_caption",
        "is_voice_design_emoji_tail_character",
        "strip_trailing_voice_design_emojis",
        "suggest_theme_completion",
        "suggest_voice_design_completion",
        "theme_suggestion_guidance",
    ],
)

from __future__ import annotations

from server.app_deps import Any, HTTPException
from server.registry import deps


def line_assistant_context(
    project: dict[str, Any], request: deps.LineAssistantRequest
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    scene = next((item for item in project.get("scenes", []) if item.get("id") == request.scene_id), None)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    lines = scene.get("lines", [])
    insert_index = len(lines)
    if request.before_line_id:
        insert_index = next((index for index, line in enumerate(lines) if line.get("id") == request.before_line_id), -1)
        if insert_index < 0:
            raise HTTPException(status_code=404, detail="Insertion position was not found.")
    character_names = {item.get("id"): item.get("name", "") for item in project.get("characters", [])}
    nearby = lines[max(0, insert_index - 3) : min(len(lines), insert_index + 3)]
    context = [
        {
            "character_id": line.get("characterId"),
            "speaker": character_names.get(line.get("characterId"), ""),
            "text": line.get("text", ""),
            "stage_direction": line.get("stageDirection", ""),
            "speech_rate": line.get("speechRate"),
            "gap_seconds": line.get("gapSeconds"),
        }
        for line in nearby
    ]
    return (scene, insert_index, context)


def line_assistant_completion(request: deps.LineAssistantRequest, *, refine_only: bool) -> dict[str, Any]:
    project = deps.read_project()
    _, _, context = line_assistant_context(project, request)
    character = deps.find_character(project, request.character_id)
    mode = "instruction" if refine_only else "generate"
    debug_directory = deps.draft_debug_directory(f"line-assistant-{mode}-{deps.new_id('request')}")
    all_characters = [
        {"id": item.get("id"), "name": item.get("name"), "profile": item.get("profile", "")}
        for item in project.get("characters", [])
    ]
    involved_ids = list(dict.fromkeys([
        request.character_id,
        *(str(row.get("character_id", "")) for row in context if row.get("character_id")),
    ]))
    involved = [item for item in project.get("characters", []) if str(item.get("id", "")) in involved_ids]
    aliases = deps.draft_cast_aliases(involved)
    cast_context = deps.draft_cast_context(involved, cast_alias_by_id=aliases)
    emoji_guidance, filler_guidance = deps.draft_expression_guidance(request)
    if refine_only:
        system = "あなたは日本語の音声台本を作るための要件整理担当です。曖昧な追加要望を直後の台本生成AIへ渡せる具体的な依頼文に整える。既存文脈と矛盾させず、キャスト・目的・応答関係・感情・演技・必要なら間を明確にする。作者が明示していないエコー・リバーブ・残響などの音響効果を追加しない。台詞は書かない。"
        user = {
            "user_request": request.instruction,
            "target_character": {"name": character.get("name"), "profile": character.get("profile", "")},
            "requested_line_count": request.line_count,
            "nearby_script_context": context,
        }
        result = deps.complete_records(
            request,
            contract=deps.instruction_contract(),
            system=system,
            user=user,
            max_tokens=900,
            temperature=0.45,
            debug_response_path=debug_directory / "attempt-1.txt",
        )
        instruction = next((row.get("value") for row in result.records if row.get("value")), None)
        if not instruction:
            raise RuntimeError("LLM did not return an improved instruction.")
        return {"instruction": instruction}
    policy = deps.performance_direction_policy(request)
    system = f"あなたは日本語の音声ドラマ脚本家・演出家です。指定位置の前後につながる、requested_line_countで指定された行数ちょうどの連続発話を作る。少ない行数で終えず、各行を短くしても指定数を必ず満たす。発話キャストはtarget_characterだけに固定する。{filler_guidance} {emoji_guidance}\n{deps.performance_direction_prompt_rules(policy)}"
    user = {
        "target_character": {
            "id": character.get("id"),
            "name": character.get("name"),
            "profile": character.get("profile", ""),
        },
        "instruction": request.instruction,
        "requested_line_count": request.line_count,
        "nearby_script_context": context,
        "participating_casts": cast_context,
        "default_speech_rate": request.speech_rate,
        "default_gap_seconds": request.line_gap,
    }
    user["all_characters"] = all_characters
    result = deps.complete_records(
        request,
        contract=deps.assistant_line_contract(),
        system=system,
        user=user,
        max_tokens=1200,
        temperature=0.7,
        debug_response_path=debug_directory / "attempt-1.txt",
    )
    raw = result.raw_response if result.mode == "legacy" else deps.project_assistant_lines(result.records)
    parsed = deps.parse_generated_lines(raw)
    if not parsed:
        raise RuntimeError("LLM did not return usable dialogue lines.")
    accepted = parsed[: request.line_count]
    missing = request.line_count - len(accepted)
    if missing > 0:
        retry_result = deps.complete_records(
            request,
            contract=deps.assistant_line_contract(),
            system=system,
            user={
                "target_character": user["target_character"],
                "instruction": request.instruction,
                "accepted_lines_immutable": accepted,
                "nearby_script_context_immutable": context,
                "participating_casts": cast_context,
                "requested_line_count": missing,
                "format_correction": "不足分だけをLINE形式で返し、accepted_lines_immutableは変更・再出力しない。",
            },
            max_tokens=1200,
            temperature=0.7,
            debug_response_path=debug_directory / "attempt-2.txt",
        )
        retry_raw = (retry_result.raw_response if retry_result.mode == "legacy"
                     else deps.project_assistant_lines(retry_result.records))
        accepted.extend((deps.parse_generated_lines(retry_raw) or [])[:missing])
    return {"lines": accepted}


@deps.app.post("/api/drafts/theme-suggestion")
def suggest_draft_theme(request: deps.ThemeSuggestionApiRequest) -> dict[str, str]:
    request = deps.ThemeSuggestionRequest.model_validate(request.model_dump())
    return deps.track_default_llm_usage("テーマ提案", lambda: {"theme": deps.suggest_theme_completion(request)})


@deps.app.post("/api/lines/assistant/suggest")
def suggest_line_insert(request: deps.LineAssistantApiRequest) -> dict[str, str]:
    request = deps.LineAssistantRequest.model_validate(request.model_dump())
    try:
        return deps.track_default_llm_usage("台詞指示の整理", lambda: line_assistant_completion(request, refine_only=True))
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@deps.app.post("/api/lines/assistant/generate")
def generate_line_insert(request: deps.LineAssistantApiRequest) -> dict[str, Any]:
    request = deps.LineAssistantRequest.model_validate(request.model_dump())
    if deps.active_draft_job() or deps.active_export_job():
        raise HTTPException(status_code=409, detail="実行中の台本生成またはエクスポートが完了してから追加してください。")
    return deps.track_default_llm_usage("台詞追加", lambda: _generate_line_insert(request))


def _generate_line_insert(request: deps.LineAssistantRequest) -> dict[str, Any]:
    try:
        raw = line_assistant_completion(request, refine_only=False)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    project = deps.read_project()
    scene, insert_index, _ = line_assistant_context(project, request)
    raw_lines = raw.get("lines", [])
    if isinstance(raw_lines, list):
        canonical_records = [
            ({"text": str(line.get("text", ""))}, dict(line.get("direction_values", {})))
            for line in raw_lines if isinstance(line, dict)
        ]
        normalized_values = iter(deps.normalize_negative_gap_ownership(
            canonical_records, default_gap=request.line_gap
        ))
    else:
        normalized_values = iter(())
    lines = []
    for raw_line in raw_lines[: request.line_count] if isinstance(raw_lines, list) else []:
        if not isinstance(raw_line, dict):
            continue
        text = deps.strip_draft_emojis(raw_line.get("text", "")).strip()
        if not text:
            continue
        values = next(normalized_values, {})
        if not values:
            legacy_text = deps.apply_llm_emoji_annotations(
                text, raw_line.get("emoji_annotations", []), enabled=request.emoji_expressions,
                allowed=deps.ai_allowed_emojis(request, deps.IRODORI_EMOJIS),
            )
            values = {
                "rate": str(raw_line.get("speech_rate", "")),
                "gap": str(raw_line.get("gap_seconds", "")),
                "direction": str(raw_line.get("stage_direction", "")),
            }
        else:
            legacy_text = text
        patch = deps.apply_performance_direction(
            deps.performance_direction_policy(request), {"text": legacy_text}, values,
            character_id=request.character_id,
        )
        directed_text = deps.enforce_tutting_intent(
            str(patch.get("text", legacy_text)), str(patch.get("stageDirection", ""))
        )
        line = {"id": deps.new_id("line"), "characterId": request.character_id, "text": directed_text,
                "speechRate": patch.get("speechRate", request.speech_rate),
                "gapSeconds": patch.get("gapSeconds", request.line_gap),
                "takes": [], "selectedTakeId": None}
        if patch.get("stageDirection"):
            line["stageDirection"] = patch["stageDirection"]
        lines.append(line)
    if not lines:
        raise HTTPException(status_code=502, detail="LLM did not return a usable dialogue line.")
    scene["lines"][insert_index:insert_index] = lines
    deps.write_project(project)
    return project


@deps.app.post("/api/characters/voice-design-suggestion")
def suggest_voice_design(request: deps.VoiceDesignSuggestionApiRequest) -> dict[str, Any]:
    request = deps.VoiceDesignSuggestionRequest.model_validate(request.model_dump())
    return deps.track_default_llm_usage("Voice Design提案", lambda: deps.suggest_voice_design_completion(request))


@deps.app.post("/api/characters/profile-suggestion")
def suggest_character_profile(request: deps.CharacterProfileSuggestionApiRequest) -> dict[str, Any]:
    request = deps.CharacterProfileSuggestionRequest.model_validate(request.model_dump())
    return deps.track_default_llm_usage("キャスト設定提案", lambda: deps.suggest_character_profile_completion(request))


deps.register(
    __name__,
    [
        "generate_line_insert",
        "line_assistant_completion",
        "line_assistant_context",
        "suggest_character_profile",
        "suggest_draft_theme",
        "suggest_line_insert",
        "suggest_voice_design",
    ],
)

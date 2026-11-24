from __future__ import annotations

from pathlib import Path
from typing import Any

from server.draft_protocol import parse_dialogue_protocol
from server.modules.script_assistant_plan_helpers import _summary_context, _compact_plan_rows, _fit_rewrite_plan_user, _normalize_proposal_cues, _original_target_context
from server.modules.script_assistant_apply import apply_script_assistant_proposal
from server.modules.script_assistant_cast_composition import (
    cast_composition_changes, cast_composition_original, cast_composition_warnings, restore_cast_composition_emojis, rewrite_original,
)
from server.modules.script_assistant_cast_generation import generate_cast_composition_rows
from server.modules.script_assistant_intent import _minimum_simultaneous_lines, _simultaneous_requirement
from server.modules.script_assistant_prompt import _author_instruction, _system_prompt
from server.modules.script_assistant_fitting import context_limit, fits, output_reservation
from server.modules.script_assistant_context_packing import explicit_reference_ids, pack_script_assistant_context
from server.modules.script_assistant_summary import summarize_rewrite_target
from server.registry import deps
from server.modules.job_publication import public_job

__all__ = ["apply_script_assistant_proposal"]
def _alias(index: int) -> str:
    value = ""
    while True:
        value = chr(65 + index % 26) + value
        index = index // 26 - 1
        if index < 0:
            return value
def public_script_assistant_job(job: dict[str, Any]) -> dict[str, Any]:
    return public_job(job, {"request", "sourceProject"})
def active_script_assistant_job() -> bool:
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        return any(job.get("status") in {"planning", "generating"} for job in deps.SCRIPT_ASSISTANT_JOBS.values())
def _update(job_id: str, **patch: Any) -> None:
    public = None
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        if job_id in deps.SCRIPT_ASSISTANT_JOBS:
            deps.SCRIPT_ASSISTANT_JOBS[job_id].update(patch)
            public = public_script_assistant_job(deps.SCRIPT_ASSISTANT_JOBS[job_id])
    if public is not None:
        deps.PROGRESS_EVENTS.observe(public)
def _cancelled(job_id: str) -> bool:
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        return bool(deps.SCRIPT_ASSISTANT_JOBS.get(job_id, {}).get("cancelRequested"))
def _call(request: Any, job_id: str, *, system: str, user: dict[str, Any], max_tokens: int,
          temperature: float, path: Path, feature: str) -> str:
    if _cancelled(job_id):
        raise deps.GenerationCancelled("AI台本編集をキャンセルしました。")
    return deps.complete_text(
        request, contract=deps.TEXT_CONTRACTS[feature], system=system, user=user,
        max_tokens=max_tokens, temperature=temperature,
        debug_response_path=path, should_cancel=lambda: _cancelled(job_id), job_id=job_id, feature=feature,
    )
def _cast_payload(
    project: dict[str, Any], request: Any, reference_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    included = {*request.character_ids, *(reference_ids or set())}
    characters = [item for item in project.get("characters", []) if str(item.get("id", "")) in included]
    aliases = {str(character.get("id", "")): _alias(index) for index, character in enumerate(characters)}
    contexts = project.get("scriptCastContexts", {})
    compiled, _audit = deps.compile_cast_context(
        request, characters, project_id=str(project.get("id", "default")), aliases=aliases,
    )
    payload = []
    for item, character in zip(deps.draft_dialogue_cast_context(compiled), characters):
        character_id = str(character.get("id", ""))
        candidate = character_id in request.character_ids
        item = {**item, "alias": item.pop("cast", aliases[character_id]),
                "script_context": contexts.get(character_id),
                "generation_candidate": candidate}
        if candidate:
            item["profile_details"] = item.get("exact_profile", {})
        else:
            item.pop("exact_profile", None)
            item.pop("summary", None)
            item.pop("relations", None)
            item.pop("preferences", None)
        payload.append(item)
    return payload, aliases
def _cast_subset(cast: list[dict[str, Any]], aliases: dict[str, str], character_ids: set[str]) -> list[dict[str, Any]]:
    wanted_aliases = {aliases[item] for item in character_ids if item in aliases}
    return [item for item in cast if str(item.get("alias", "")) in wanted_aliases]
def _dialogue_call(request: Any, job_id: str, *, system: str, user: dict[str, Any], max_tokens: int,
                   temperature: float, path: Path, existing_rows: list[dict[str, Any]]) -> tuple[str, str]:
    try:
        return _call(
            request, job_id, system=system, user=user, max_tokens=max_tokens, temperature=temperature,
            path=path, feature="script-assistant-dialogue",
        ), ""
    except deps.GenerationCancelled:
        raise
    except Exception as error:
        if existing_rows:
            return "", f"後続区間を生成できなかったため部分提案です: {error}"
        raise
def _dialogue_temperature(operation: str) -> float:
    return {"cast-compose": 0.35, "paraphrase": 0.55, "rewrite": 0.8}.get(operation, 0.7)


def _required_simultaneous(request, required):
    return _simultaneous_requirement(request) if required else ""


def _rewrite_plan(request: Any, job_id: str, project: dict[str, Any], group: dict[str, Any],
                  context: dict[str, Any], older_summary: str, debug: Path,
                  group_index: int, group_total: int, simultaneous_requirement: str) -> str:
    reference_ids = explicit_reference_ids(project, request.instruction) | context["_reference_ids"]
    cast, _aliases = _cast_payload(project, request, reference_ids)
    cast_index = [
        {"alias": item.get("alias"), "name": item.get("name"), "role": item.get("script_context") or "指定なし"}
        for item in cast
    ]
    _update(
        job_id, status="planning", phase="rewrite-plan",
        message=f"{group_index}/{group_total} シーンの書き直し方針を組み立てています…",
        overallProgress=min(30, 10 + 20 * group_index / group_total),
    )
    system = (
        "あなたは日本語音声ドラマの書き直し構成担当です。台詞本文は執筆せず、対象範囲を別の会話経路で"
        "再構成するための短い方針だけを書く。元台詞、前の確定文脈、後続3行、キャスト設定、作者の要望から、"
        "守るべき事実と意図、会話後の到達点、別の会話経路、避ける反復を整理する。飛び飛びの選択では、"
        "未選択アンカーを変更せず、各置換位置が担う役割を順番に明記する。作者の要望を変更方針として優先するが、"
        "前後との整合は壊さない。要望が空でも、新しい不可逆な設定や唐突な事件を足さず、入口、話題の運び、"
        "応答順、感情の推移を元とは異なる形にする。元台詞の引用や言い換え、完成台詞、JSON、Markdownは禁止。"
        "途中まででも利用できる、簡潔な日本語本文だけを返す。" +
        (" 同時発話要件は省略せず、発話順と参加話者の役割を方針へ明記する。" if simultaneous_requirement else "")
    )
    original_rows = _compact_plan_rows(context["selected"])
    target_summaries = summarize_rewrite_target(
        request, job_id, str(project.get("id", "")), str(group["id"]), context["selected"], debug, call=_call,
    )
    if target_summaries:
        original_rows = []
    plan_user = _fit_rewrite_plan_user(system, {
            "author_instruction": request.instruction.strip() or "指定なし",
            "simultaneous_requirement": simultaneous_requirement or "指定なし",
            "selected_cast_index": cast_index, **_summary_context(context),
            "recent_confirmed_context": context["recent"],
            "original_target_rows": original_rows,
            **({"target_segment_summaries": target_summaries} if target_summaries else {}),
            "immutable_rows_inside_selection": _compact_plan_rows(context["anchors"]),
            "following_three_rows": _compact_plan_rows(context["following"]),
            "fixed_replacement_count": len(group["originalLines"]) if group["fixed"] else None,
            "target_line_count": group.get("targetLineCount"),
            "target_spoken_characters": group.get("targetCharacters"),
        })
    minimum_plan_output = 256
    if not fits(system, plan_user, minimum_plan_output):
        input_tokens = deps.estimate_llm_input_tokens(system, plan_user)
        safety = deps.DRAFT_CONTEXT_SAFETY_MARGIN
        required = input_tokens + minimum_plan_output + safety
        raise RuntimeError(
            "書き直し方針の必須ContextがモデルのContext上限へ収まりません"
            f"（入力約{input_tokens}、最小出力予約{minimum_plan_output}、安全余白{safety}、"
            f"必要約{required}、上限{context_limit()}トークン）。")
    raw = _call(
        request, job_id, system=system, user=plan_user, max_tokens=1400, temperature=0.35,
        path=debug / f"group-{group_index}-rewrite-plan.txt", feature="script-assistant-rewrite-plan",
    ).strip()
    if not raw:
        raise RuntimeError("LLMから利用できる書き直し方針を取得できませんでした。")
    return raw


def _direct_rows(request: Any, parsed: list[dict[str, Any]], original: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = [(row, dict(row.get("integrated_direction", {}))) for row in parsed]
    values = deps.normalize_negative_gap_ownership(records, default_gap=request.line_gap)
    policy = deps.performance_direction_policy(request)
    rows: list[dict[str, Any]] = []
    for index, (raw, direction) in enumerate(zip(parsed, values, strict=True)):
        text = deps.strip_draft_emojis(str(raw.get("text", ""))).strip()
        if not text:
            continue
        source = None
        if request.operation in {"cast-compose", "paraphrase"}:
            source = cast_composition_original(raw, index, len(parsed), original)
            if request.operation == "paraphrase":
                source = rewrite_original(raw, original)
            if source is None:
                continue
            if request.operation == "cast-compose":
                text = restore_cast_composition_emojis(str(raw.get("text", "")), str(source.get("text", "")))
        character_id = str(raw.get("character_id", ""))
        if request.operation == "paraphrase" and source is not None:
            character_id = str(source.get("characterId", ""))
        elif source is not None:
            character_id = str(source.get("characterId", ""))
        patch = deps.apply_performance_direction(policy, {"text": text}, direction, character_id=character_id)
        intent_direction = str(source.get("stageDirection", "")) if source is not None else str(patch.get("stageDirection", ""))
        directed = deps.enforce_tutting_intent(str(patch.get("text", text)), intent_direction)
        row = {
            "id": deps.new_id("assistant_row"), "characterId": character_id, "text": directed,
            "stageDirection": str(patch.get("stageDirection", "")),
            "speechRate": patch.get("speechRate", request.speech_rate),
            "gapSeconds": patch.get("gapSeconds", request.line_gap),
            "cueMarker": str(patch.get("simultaneous_marker", "")),
        }
        if source is not None:
            row.update({
                "originalLineId": str(source.get("id", "")),
                "stageDirection": str(source.get("stageDirection", "")),
                "speechRate": source.get("speechRate"), "gapSeconds": source.get("gapSeconds"),
            })
        rows.append(row)
    if request.operation != "paraphrase":
        return rows
    # A model can repeat or reorder independently addressable rewrite records.
    # Keep the first usable record for each source row, then restore project
    # order so a malformed sibling cannot change row ownership in the preview.
    order = {str(row.get("id", "")): index for index, row in enumerate(original)}
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_id = str(row.get("originalLineId", ""))
        if source_id in order and source_id not in unique:
            unique[source_id] = row
    return sorted(unique.values(), key=lambda row: order[str(row["originalLineId"])])


def _proposal_group(
    request: Any, project: dict[str, Any], group: dict[str, Any], rows: list[dict[str, Any]],
    reviewed_count: int, target_lines: int, target_characters: int, simultaneous_requirement: str,
) -> dict[str, Any]:
    if not rows and not (request.operation == "cast-compose" and reviewed_count):
        raise RuntimeError("LLMから利用できる発話行を取得できませんでした。")
    if request.operation != "cast-compose" and (group["fixed"] or len(rows) == len(group["originalLines"])):
        for row, original in zip(rows, group["originalLines"], strict=False):
            row["originalLineId"] = str(original.get("id", ""))
    cue_allowed = request.operation in {"insert", "rewrite"} and group["contiguous"] and request.simultaneous_cues
    _normalize_proposal_cues(rows, allowed=cue_allowed)
    atomic = request.operation == "rewrite" and group["contiguous"] and len(rows) != len(group["originalLines"])
    warnings = cast_composition_warnings(request.operation, reviewed_count, target_lines, bool(rows))
    if simultaneous_requirement and not any(row.get("proposalCueId") for row in rows):
        warnings.append("指定された同時発話を提案内に構成できませんでした。この提案は同時発話の要望を満たしていません。")
    if target_lines and request.operation != "cast-compose" and len(rows) < target_lines:
        warnings.append(f"目標{target_lines}行のうち{len(rows)}行を提案しました。")
    if target_characters and sum(len(deps.strip_draft_emojis(row["text"])) for row in rows) < target_characters:
        warnings.append("指定した分量より短い部分提案です。")
    names = {str(item.get("id", "")): str(item.get("name", "")) for item in project.get("characters", [])}
    for row in rows:
        row["characterName"] = names.get(row["characterId"], "")
    return {
        "id": group["id"], "sceneId": group["sceneId"], "sceneTitle": group["sceneTitle"],
        "atomic": atomic, "contiguous": group["contiguous"], "rows": rows,
        "originalRows": [{
            "id": line.get("id"), "characterId": line.get("characterId"),
            "characterName": names.get(str(line.get("characterId", "")), ""), "text": line.get("text", ""),
            "stageDirection": line.get("stageDirection", ""), "enabled": line.get("enabled", True),
            "hasTakes": bool(line.get("takes")),
        } for line in group["originalLines"]],
        "warnings": warnings, "insertIndex": group["insertIndex"], "targetLineIds": group["targetLineIds"],
    }


def _generate_group(request: Any, job_id: str, project: dict[str, Any], group: dict[str, Any],
                    context: dict[str, Any], debug: Path, group_index: int, group_total: int,
                    *, requires_simultaneous: bool) -> dict[str, Any]:
    context = pack_script_assistant_context(request, job_id, context, debug, call=_call)
    reference_ids = set(context["_reference_ids"])
    reference_ids.update(explicit_reference_ids(project, request.instruction))
    cast, aliases = _cast_payload(project, request, reference_ids)
    if request.operation in {"paraphrase", "cast-compose"}:
        speaking = {str(row.get("characterId", "")) for row in group["originalLines"]}
        cast = _cast_subset(cast, aliases, speaking | reference_ids)
    alias_to_id = {alias: character_id for character_id, alias in aliases.items()}
    summary = "\n".join(
        [*(item["summary"] for item in context["distant_context"]), context["middle_context"]]
    ).strip()
    simultaneous_requirement = _required_simultaneous(request, requires_simultaneous)
    rewrite_plan = _rewrite_plan(
        request, job_id, project, group, context, summary, debug, group_index, group_total,
        simultaneous_requirement,
    ) if request.operation == "rewrite" else ""
    target_lines = int(group.get("targetLineCount", 0))
    if simultaneous_requirement and request.target_kind == "lines":
        target_lines = max(_minimum_simultaneous_lines(request), target_lines)
    target_characters = int(group.get("targetCharacters", 0))
    rows: list[dict[str, Any]] = []
    reviewed_count = 0
    generation_warning = ""
    if request.operation == "cast-compose":
        rows, reviewed_count, generation_warning = generate_cast_composition_rows(
            request, job_id, group, context, cast, alias_to_id, summary, debug, group_index, group_total,
            call=_call, update=_update, direct_rows=_direct_rows,
        )
        attempts = 0
    else:
        attempts = 0
    pending_fixed = list(group["originalLines"]) if request.operation == "paraphrase" else []
    recent_context = context["recent"]
    while request.operation != "cast-compose":
        remaining_lines = len(pending_fixed) if pending_fixed else max(0, target_lines - len(rows))
        remaining_characters = max(0, target_characters - sum(len(deps.strip_draft_emojis(row["text"])) for row in rows))
        if (target_lines and remaining_lines == 0) or (target_characters and remaining_characters == 0):
            break
        requested = remaining_lines if target_lines else max(1, (remaining_characters + 54) // 55)
        attempts += 1
        _update(job_id, status="generating", phase="dialogue", message=f"{group_index}/{group_total} シーンの提案を生成しています…",
                overallProgress=min(90, 10 + 80 * ((group_index - 1) + min(1, len(rows) / max(1, target_lines))) / group_total))

        def build_generation_context(count: int) -> dict[str, Any]:
            selected = pending_fixed[:count] if pending_fixed else context["selected"]
            value = {
                "author_instruction": _author_instruction(request),
                "selected_casts": cast, "requested_line_count": count,
                "target_spoken_characters_remaining": remaining_characters or None,
                "recent_confirmed_context": recent_context,
                "immutable_rows_inside_selection": context["anchors"],
                "following_three_rows": context["following"], "accepted_continuation_tail": rows[-5:],
                "simultaneous_requirement": simultaneous_requirement or "指定なし",
                **_summary_context(context),
            }
            value.update(_original_target_context(request, selected, group["originalLines"]))
            if rewrite_plan:
                value["rewrite_plan"] = rewrite_plan
            return value

        system = _system_prompt(request, group, simultaneous_requirement)
        while requested > 1 and not fits(system, build_generation_context(requested), output_reservation(requested)):
            requested = max(1, requested // 2)
        generation_context = build_generation_context(requested)
        if not fits(system, generation_context, output_reservation(requested)):
            raise RuntimeError("近接・人物・編集対象Contextと出力予約がモデルのContext上限へ収まりません。")
        raw, generation_warning = _dialogue_call(
            request, job_id, system=system, user=generation_context,
            max_tokens=output_reservation(requested), temperature=_dialogue_temperature(request.operation),
            path=debug / f"group-{group_index}-attempt-{attempts}.txt", existing_rows=rows,
        )
        parsed = parse_dialogue_protocol(
            raw, allowed_speakers=set(request.character_ids), speaker_aliases=alias_to_id
        ).get("lines", [])
        accepted = _direct_rows(request, parsed, group["originalLines"])
        if pending_fixed:
            processed_ids = {str(item.get("id", "")) for item in pending_fixed[:requested]}
            accepted = [row for row in accepted if str(row.get("originalLineId", "")) in processed_ids]
        if not accepted:
            break
        accepted, reviewed = cast_composition_changes(request.operation, accepted, group["originalLines"])
        reviewed_count += reviewed
        rows.extend(accepted[:remaining_lines] if target_lines else accepted)
        if pending_fixed:
            accepted_ids = {str(row.get("originalLineId", "")) for row in accepted}
            processed = pending_fixed[:requested]
            pending_fixed = pending_fixed[requested:]
            missing = [item for item in processed if str(item.get("id", "")) not in accepted_ids]
            pending_fixed.extend(missing)
            if missing and not accepted_ids:
                break
    proposal = _proposal_group(
        request, project, group, rows, reviewed_count, target_lines, target_characters, simultaneous_requirement,
    )
    if generation_warning:
        proposal["warnings"].append(generation_warning)
    return proposal


def run_script_assistant_job(job_id: str, request: Any, project: dict[str, Any]) -> None:
    debug = deps.draft_debug_directory(job_id)
    try:
        deps.activate_script_assistant_context(job_id, request)
        groups = deps.prepare_script_assistant_groups(project, request)
        simultaneous_requirement = _simultaneous_requirement(request)
        if simultaneous_requirement:
            if not request.simultaneous_cues:
                raise RuntimeError("同時発話の明示要望には「同時発話の提案を許可」が必要です。")
            if len(request.character_ids) < 2:
                raise RuntimeError("同時発話の明示要望には生成対象キャストが2人以上必要です。")
            if not any(group["contiguous"] for group in groups):
                raise RuntimeError("飛び飛びの行選択では同時発話を新しく構成できません。")
        simultaneous_group_index = next(
            (index for index, group in enumerate(groups, 1) if group["contiguous"]), None,
        ) if simultaneous_requirement else None
        signature = deps.script_assistant_signature(project, request)
        _update(job_id, phase="context", message="台本の文脈を整理しています…", overallProgress=5)
        proposals = []
        generation_warnings: list[str] = []
        for index, group in enumerate(groups, 1):
            if _cancelled(job_id):
                raise deps.GenerationCancelled("AI台本編集をキャンセルしました。")
            context = deps.script_assistant_context(project, group)
            try:
                proposals.append(_generate_group(
                    request, job_id, project, group, context, debug, index, len(groups),
                    requires_simultaneous=index == simultaneous_group_index,
                ))
            except deps.GenerationCancelled:
                raise
            except Exception as error:
                if not proposals:
                    raise
                generation_warnings.append(
                    f"{index}/{len(groups)} シーン目は提案を生成できませんでした: {error}"
                )
                break
        if _cancelled(job_id):
            raise deps.GenerationCancelled("AI台本編集をキャンセルしました。")
        proposal_id = deps.new_id("assistant_proposal")
        proposal = {"id": proposal_id, "jobId": job_id, "createdAt": deps.now_ms(),
                    "sourceSignature": signature, "request": request.model_dump(), "groups": proposals}
        with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
            deps.SCRIPT_ASSISTANT_PROPOSALS[proposal_id] = proposal
        warnings = [warning for group in proposals for warning in group["warnings"]] + generation_warnings
        message = "一部の提案を確認できます。" if generation_warnings else "提案を確認できます。"
        _update(job_id, status="completed", phase="completed", message=message,
                overallProgress=100, proposalId=proposal_id, sourceSignature=signature, groups=proposals,
                warnings=warnings, completedAt=deps.now_ms())
    except deps.GenerationCancelled:
        _update(job_id, status="cancelled", phase="cancelled", message="生成をキャンセルしました。台本は変更していません。",
                completedAt=deps.now_ms())
    except Exception as error:
        _update(job_id, status="failed", phase="failed", message=f"提案を生成できませんでした: {error}",
                error=type(error).__name__, completedAt=deps.now_ms())
    finally:
        deps.clear_script_assistant_context()
deps.register(__name__, [
    "active_script_assistant_job", "public_script_assistant_job", "run_script_assistant_job",
])

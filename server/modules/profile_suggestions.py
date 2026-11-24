from __future__ import annotations

import json
from dataclasses import replace

from server.app_deps import Any, HTTPException
from server.registry import deps

PROFILE_FIELDS = {
    "familyName": "苗字", "familyNameKana": "苗字のふりがな", "givenName": "名前",
    "givenNameKana": "名前のふりがな", "aliases": "愛称", "age": "年齢", "bloodType": "血液型",
    "birthDate": "誕生日", "birthplace": "出身地", "residence": "居住地", "gender": "性別",
    "role": "職業", "firstPerson": "一人称", "secondPerson": "二人称",
    "defaultAddressBasis": "呼び方の基準", "defaultHonorific": "基本の敬称",
    "defaultAddressNote": "呼び方の補足", "skills": "特技", "hobbies": "趣味", "likes": "好きなもの",
    "dislikes": "苦手なもの", "personality": "性格", "speechStyle": "基本の口調",
    "background": "背景・来歴", "otherRelationships": "その他の人間関係",
}
IDENTITY_FIELDS = {"familyName", "familyNameKana", "givenName", "givenNameKana", "aliases"}
PROFILE_SYSTEM = """あなたは日本語の創作キャラクター設定を作る編集者です。作者の自由メモと追加アイディアを最優先し、requested_fieldsに指定された項目だけを一人の人物として整合する具体的な値で提案する。ensemble_contextを同じ作品の既存キャストとして考慮し、人物像と名前の取り合わせが単調にならないよう全体の多様性を作る。used_identity_valuesにある表示名・姓・名・愛称、および既存キャストと同じ姓名の組合せは再使用禁止。性格から典型名を機械的に連想せず、たとえば荒っぽい人物だから「剛田」とするような固定観念による命名を避ける。未設定、不明、なし、N/A、仮置きは禁止。誕生日は「4月18日」、ふりがなはひらがな。配列値は／で区切る。表示名やrequested_fields以外の項目は提案しない。"""
RELATION_SYSTEM = """あなたは日本語の創作キャラクター設定を作る編集者です。人物核と作者のアイディアを不変の前提として、この人物から指定相手へ向く関係だけを提案する。relation_targetsのmissing_relation_fieldsだけを独立に返す。
呼び方は名前・愛称を既定とし、advertised address_candidatesとhonorificsのIDを選ぶ。basisは候補のkindと一致させる。人物設定を順番に呼称化してはならない。職業、性格、背景、趣味、物語上の役割は「設定にある」「特徴的」というだけでは呼称にしない。
設定由来の特別な呼称を実際の関係上使う場合だけ、敬称を除くcustomとhonorific IDを選ぶ。basisのformal_titleは「王子様」のように身分・職位・社会的肩書として呼ぶ場合、relational_nicknameは二人の関係で実際に成立するあだ名だけにする。「文学少女ちゃん」「調停役さん」のような人物紹介ラベルは選ばない。候補にない完成呼称は作らない。"""


def _cast_prompt_name(cast: dict[str, Any], fallback: str) -> str:
    display = str(cast.get("name", "")).strip()[:80]
    if display:
        return display
    details = deps.normalize_character_profile_details(cast.get("profile_details"))
    aliases = details.get("aliases", [])
    if isinstance(aliases, list):
        alias = next((str(value).strip()[:80] for value in aliases if str(value).strip()), "")
        if alias:
            return alias
    full_name = "".join(str(details.get(field, "")).strip()[:40] for field in ("familyName", "givenName"))
    return full_name or fallback


def _relation_targets(request, details: dict[str, Any]) -> list[dict[str, Any]]:
    existing = details.get("castRelations", {})
    targets = []
    for cast in request.other_casts:
        cast_id = str(cast.get("id", "")).strip()[:120]
        if not cast_id:
            continue
        name = _cast_prompt_name(cast, f"キャスト（{cast_id}）")
        relation = existing.get(cast_id, {}) if isinstance(existing, dict) else {}
        relation = relation if isinstance(relation, dict) else {"relationship": relation}
        current = {key: str(relation.get(key, "")).strip() for key in ("address", "relationship")}
        missing = list(current) if request.mode == "replace_details" else [key for key, value in current.items() if not value]
        if missing:
            target_details = deps.normalize_character_profile_details(cast.get("profile_details"))
            target_details.pop("castRelations", None)
            reference = deps.character_relation_reference({
                "profile": str(cast.get("profile", "")).strip()[:2000],
                "profileDetails": target_details,
            })
            target = {"id": cast_id, "name": name, "relationship_reference": reference,
                      "source_cast": cast,
                      "missing_relation_fields": missing}
            if immutable := {key: value for key, value in current.items() if key not in missing and value}:
                target["existing_relation"] = immutable
            if "address" in missing and request.mode == "replace_details":
                normalized, reason = deps.normalize_known_address(current["address"])
                if reason == "known_unnatural_combination" and normalized:
                    target["normalized_existing_address"] = normalized
            targets.append(target)
    return targets


def _identity_key(value: object) -> str:
    return "".join(str(value).split()).casefold()


def _other_cast_identity_context(request) -> tuple[list[dict[str, Any]], dict[str, list[str]], set[str]]:
    ensemble: list[dict[str, Any]] = []
    used = {"displayNames": [], "familyNames": [], "givenNames": [], "aliases": [], "fullNames": []}
    all_values: set[str] = set()
    for cast in request.other_casts:
        details = deps.normalize_character_profile_details(cast.get("profile_details"))
        display = _cast_prompt_name(cast, "名称未設定のキャスト")
        family = str(details.get("familyName", "")).strip()[:80]
        given = str(details.get("givenName", "")).strip()[:80]
        aliases = [str(value).strip()[:80] for value in details.get("aliases", [])[:8] if str(value).strip()]
        full_name = "".join((family, given))
        values = {"displayNames": [display], "familyNames": [family], "givenNames": [given],
                  "aliases": aliases, "fullNames": [full_name]}
        for key, items in values.items():
            accepted = [value for value in items if value]
            used[key].extend(accepted)
            all_values.update(_identity_key(value) for value in accepted)
        ensemble.append({"display_name": display, "family_name": family, "given_name": given,
                         "aliases": aliases, "role": str(details.get("role", "")).strip()[:300],
                         "personality": str(details.get("personality", "")).strip()[:300]})
    return ensemble, used, all_values


def _profile_user(request, details: dict[str, Any], blank: list[str]) -> dict[str, Any]:
    existing = {PROFILE_FIELDS[key]: "／".join(value) if isinstance(value, list) else value
                for key, value in details.items() if key in PROFILE_FIELDS and key not in blank and value}
    ensemble, used, _ = _other_cast_identity_context(request)
    subject_name = _cast_prompt_name({"name": request.name, "profile_details": details}, "名称未設定のキャスト")
    return {"character_name": subject_name,
            "existing_settings": existing if request.mode == "fill_missing" else {},
            "existing_free_memo": request.profile.strip() or "（未設定）",
            "author_idea": request.idea.strip() or "（追加アイディアなし）",
            "ensemble_context": ensemble, "used_identity_values": used,
            "requested_fields": {key: PROFILE_FIELDS[key] for key in blank}}


def _parse_profile(content: str, blank: set[str]) -> dict[str, Any]:
    parsed = deps.parse_profile_suggestion(content, labels=PROFILE_FIELDS, blank_fields=blank,
                                           allowed_relation_names=set(), subject_name="",
                                           allowed_relation_fields={})
    return parsed[0] if parsed else {}


def _without_duplicate_identities(request, proposed: dict[str, Any]) -> dict[str, Any]:
    _, used, all_values = _other_cast_identity_context(request)
    accepted = dict(proposed)
    for field in ("familyName", "givenName"):
        value = accepted.get(field)
        if value and _identity_key(value) in all_values:
            accepted.pop(field, None)
            accepted.pop(f"{field}Kana", None)
    aliases = accepted.get("aliases")
    if isinstance(aliases, list):
        unique = [value for value in aliases if _identity_key(value) not in all_values]
        if unique:
            accepted["aliases"] = unique
        else:
            accepted.pop("aliases", None)
    family, given = accepted.get("familyName"), accepted.get("givenName")
    if family and given and _identity_key(f"{family}{given}") in {_identity_key(value) for value in used["fullNames"]}:
        for field in ("familyName", "familyNameKana", "givenName", "givenNameKana"):
            accepted.pop(field, None)
    return accepted


def _complete_profile(request, details: dict[str, Any], blank: list[str], debug_directory,
                      should_cancel=None) -> dict[str, Any]:
    if not blank:
        return {}
    user = _profile_user(request, details, blank)
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "field": {"type": "string", "enum": blank}, "value": {"type": "string"},
    }, "required": ["field", "value"]}
    def legacy(content):
        return [{"field": key, "value": "／".join(value) if isinstance(value, list) else value}
                for key, value in _parse_profile(content, set(blank)).items()]
    contract = deps.LlmRecordContract(
        "character-profile", 1, schema, "field", frozenset(blank),
        legacy_suffix="各行をFIELD|<項目キー>|<値>形式で返す。JSONや説明は出力しない。",
        legacy_parser=legacy,
    )
    result = deps.complete_records(
        request, contract=contract, system=PROFILE_SYSTEM, user=user, max_tokens=1400,
        temperature=0.55, debug_response_path=debug_directory / "profile-1.txt",
        should_cancel=should_cancel,
    )
    projected = "\n".join(f"FIELD|{row['field']}|{row['value']}" for row in result.records)
    proposed = _parse_profile(projected, set(blank))
    return deps.normalize_character_profile_details(_without_duplicate_identities(request, proposed))


def _relation_user(request, core: dict[str, Any], targets: list[dict[str, Any]], registries) -> dict[str, Any]:
    subject_name = _cast_prompt_name({"name": request.name, "profile_details": core}, "名称未設定のキャスト")
    return {"character_id": subject_name, "immutable_character_core": core,
            "author_idea": request.idea.strip() or "（追加アイディアなし）",
            "relation_targets": [deps.prompt_address_options(item, registries[item["id"]]) for item in targets],
            "completion_rule": "各対象のmissing_relation_fieldsだけを独立に返す。"}


def _fitting_chunk(request, core: dict[str, Any], remaining: list[dict[str, Any]], registries) -> tuple[list[dict[str, Any]], bool]:
    for size in (6, 3, 1):
        chunk = remaining[:min(size, len(remaining))]
        try:
            deps.select_call_context(request, system=RELATION_SYSTEM,
                                     user=_relation_user(request, core, chunk, registries), max_tokens=1200)
            return chunk, True
        except RuntimeError:
            continue
    return remaining[:1], False


def _resolved_relation_result(result, chunk, registries):
    if result.mode == "schema":
        parsed, semantic_manifest = deps.resolve_relation_records(list(result.records), chunk, registries)
        return parsed, [*result.manifest, *semantic_manifest]
    return ({record["target"]: {key: value for key, value in record.items() if key != "target"}
             for record in result.records}, list(result.manifest))


def _chunked_relations(request, core: dict[str, Any], targets: list[dict[str, Any]], debug_directory,
                       progress=None, should_cancel=None) -> tuple[dict[str, Any], list[str], list[str]]:
    accepted: dict[str, Any] = {}
    for target in targets:
        if "address" not in target["missing_relation_fields"]:
            continue
        if normalized := target.get("normalized_existing_address"):
            accepted[target["id"]] = {"address": normalized}
    incomplete: list[str] = []
    warnings: list[str] = []
    registries = deps.build_address_registries(targets, core)
    remaining = list(targets)
    completed = 0
    while remaining:
        if should_cancel and should_cancel():
            if accepted:
                incomplete.extend(item["id"] for item in remaining)
                warnings.append("キャンセル前に確定した提案だけを保持しました。")
                break
            raise deps.GenerationCancelled("キャスト設定の提案をキャンセルしました。")
        chunk, fits = _fitting_chunk(request, core, remaining, registries)
        if not fits:
            incomplete.append(chunk[0]["id"])
            warnings.append(f"{chunk[0]['name']}はContext上限へ収まりませんでした。")
            remaining = remaining[1:]
            continue
        if progress:
            progress("relations", completed, len(targets))
        try:
            contract = deps.relation_record_contract(chunk, registries)
            contract = replace(contract, legacy_parser=lambda content: [
                {"target": target_id, **fields}
                for target_id, fields in deps.parse_relation_response(content, chunk, registries)[0].items()
            ])
            result = deps.complete_records(
                request, contract=contract, system=RELATION_SYSTEM,
                user=_relation_user(request, core, chunk, registries), max_tokens=1200,
                temperature=0.55, should_cancel=should_cancel,
                debug_response_path=debug_directory / f"relations-{completed + 1}.txt",
            )
        except deps.GenerationCancelled:
            if not accepted:
                raise
            incomplete.extend(item["id"] for item in remaining)
            warnings.append("キャンセル前に確定した提案だけを保持しました。")
            break
        except RuntimeError as error:
            incomplete.extend(item["id"] for item in remaining)
            warnings.append(str(error))
            break
        parsed, manifest = _resolved_relation_result(result, chunk, registries)
        if debug_directory.exists():
            (debug_directory / f"relations-{completed + 1}-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
            )
        for target_id, fields in parsed.items():
            accepted.setdefault(target_id, {}).update(fields)
        incomplete.extend(
            item["id"] for item in chunk
            if any(field not in accepted.get(item["id"], {}) for field in item["missing_relation_fields"])
        )
        completed += len(chunk)
        remaining = remaining[len(chunk):]
    if progress:
        progress("relations", completed, len(targets))
    return accepted, list(dict.fromkeys(incomplete)), warnings


def suggest_character_profile_completion(request, *, progress=None, should_cancel=None) -> dict[str, Any]:
    details = deps.normalize_character_profile_details(request.profile_details)
    profile_enabled = request.scope in {"all", "profile"}
    relations_enabled = request.scope in {"all", "relations"}
    blank = (
        list(PROFILE_FIELDS) if request.mode == "replace_details"
        else [key for key in PROFILE_FIELDS if not details.get(key)]
    ) if profile_enabled else []
    targets = _relation_targets(request, details) if relations_enabled else []
    if request.mode == "fill_missing" and not blank and not targets:
        raise HTTPException(
            status_code=422,
            detail="選択した範囲に空欄の項目がありません。生成方法を「すべて」に切り替えるか、生成範囲を変更してください。",
        )
    debug_directory = deps.draft_debug_directory(f"character-profile-suggestion-{deps.new_id('request')}")
    try:
        if progress and profile_enabled:
            progress("profile", 0, len(targets))
        profile = _complete_profile(request, details, blank, debug_directory, should_cancel) if profile_enabled else {}
        core = deps.normalize_character_profile_details({**details, **profile})
        core.pop("castRelations", None)
        relations, incomplete, warnings = (
            _chunked_relations(request, core, targets, debug_directory, progress, should_cancel)
            if relations_enabled else ({}, [], [])
        )
    except deps.GenerationCancelled:
        raise
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    suggestion = dict(profile)
    if relations:
        suggestion["castRelations"] = deps.normalize_character_profile_details({"castRelations": relations})["castRelations"]
    accepted_fields = len([key for key in suggestion if key != "castRelations"])
    accepted_relation_fields = sum(len(value) for value in relations.values())
    requested_relation_fields = sum(len(item["missing_relation_fields"]) for item in targets)
    if not accepted_fields and not accepted_relation_fields:
        raise HTTPException(status_code=502, detail="LLMから利用できるキャスト設定の提案を受け取れませんでした。")
    incomplete_fields = [f"profileDetails.{key}" for key in blank if key not in profile]
    incomplete_fields.extend(
        f"{item['id']}:{field}" for item in targets
        for field in item["missing_relation_fields"] if field not in relations.get(item["id"], {})
    )
    return {"profileDetails": suggestion, "requestedProfileFields": len(blank),
            "acceptedProfileFields": accepted_fields, "requestedRelationFields": requested_relation_fields,
            "acceptedRelationFields": accepted_relation_fields, "incompleteTargetIds": incomplete,
            "incompleteFields": incomplete_fields, "warnings": warnings}


def profile_suggestion_target_count(request) -> int:
    if request.scope == "profile":
        return 0
    details = deps.normalize_character_profile_details(request.profile_details)
    return len(_relation_targets(request, details))


deps.register(__name__, ["profile_suggestion_target_count", "suggest_character_profile_completion"])

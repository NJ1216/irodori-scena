from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from server.app_deps import HTTPException
from server.modules.script_assistant_cast_composition import validate_cast_composition_target
from server.registry import deps

VIRTUAL_CHAPTER_LINES = 50


def _timeline(project: dict[str, Any]) -> list[dict[str, Any]]:
    names = {str(item.get("id", "")): str(item.get("name", "")) for item in project.get("characters", [])}
    result: list[dict[str, Any]] = []
    for scene_order, scene in enumerate(project.get("scenes", [])):
        for line_order, line in enumerate(scene.get("lines", [])):
            result.append({
                "sceneId": str(scene.get("id", "")), "sceneTitle": str(scene.get("title", "")),
                "sceneOrder": scene_order, "lineOrder": line_order, "line": line,
                "speaker": names.get(str(line.get("characterId", "")), ""),
            })
    return result


def _chapter_key(item: dict[str, Any], *, virtual: bool) -> str:
    suffix = item["lineOrder"] // VIRTUAL_CHAPTER_LINES if virtual else 0
    return f'{item["sceneId"]}:{suffix}'


def script_assistant_signature(project: dict[str, Any], request: Any) -> str:
    # Context speakers are part of the compiled prompt even when they are not
    # generation candidates. Their profiles and relations must therefore
    # invalidate a pending proposal as well.
    selected_casts = set(request.character_ids)
    selected_casts.update(
        str(line.get("characterId", ""))
        for scene in project.get("scenes", []) for line in scene.get("lines", [])
        if str(line.get("characterId", ""))
    )
    projection = {
        "title": project.get("title", ""),
        "scenes": [
            {
                "id": scene.get("id"), "title": scene.get("title", ""),
                "lines": [{
                    key: line.get(key)
                    for key in ("id", "characterId", "text", "stageDirection", "speechRate", "gapSeconds",
                                "enabled", "cueId", "startOffsetSeconds", "targetDurationSeconds")
                } for line in scene.get("lines", [])],
            }
            for scene in project.get("scenes", [])
        ],
        "characters": [{
            key: character.get(key) for key in ("id", "name", "profile", "profileDetails")
        } for character in project.get("characters", []) if str(character.get("id", "")) in selected_casts],
        "scriptCastContexts": {
            key: value for key, value in project.get("scriptCastContexts", {}).items() if key in selected_casts
        },
        "settings": {key: project.get("settings", {}).get(key) for key in ("speechRate", "lineGap")},
    }
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _allocate_line_targets(groups: list[dict[str, Any]], total: int) -> list[int]:
    if total < len(groups):
        raise HTTPException(status_code=422, detail="行数目標は対象シーン数以上にしてください。")
    weights = [max(1, len(group["targetLineIds"])) for group in groups]
    weight_total = sum(weights)
    raw = [total * weight / weight_total for weight in weights]
    allocated = [max(1, math.floor(value)) for value in raw]
    while sum(allocated) < total:
        index = max(range(len(groups)), key=lambda item: (raw[item] - allocated[item], -item))
        allocated[index] += 1
    while sum(allocated) > total:
        index = max((item for item in range(len(groups)) if allocated[item] > 1), key=lambda item: allocated[item] - raw[item])
        allocated[index] -= 1
    return allocated


def prepare_script_assistant_groups(project: dict[str, Any], request: Any) -> list[dict[str, Any]]:
    known_casts = {str(item.get("id", "")) for item in project.get("characters", [])}
    if invalid := set(request.character_ids) - known_casts:
        raise HTTPException(status_code=422, detail=f"登録されていないキャストです: {', '.join(sorted(invalid))}")
    timeline = _timeline(project)
    if request.operation == "insert":
        scene = next((item for item in project.get("scenes", []) if str(item.get("id", "")) == request.scene_id), None)
        if scene is None:
            raise HTTPException(status_code=404, detail="挿入先シーンが見つかりません。")
        index = len(scene.get("lines", []))
        if request.before_line_id:
            index = next((i for i, line in enumerate(scene.get("lines", [])) if str(line.get("id", "")) == request.before_line_id), -1)
            if index < 0:
                raise HTTPException(status_code=404, detail="挿入位置が見つかりません。")
        groups = [{"id": deps.new_id("assistant_group"), "sceneId": request.scene_id,
                   "sceneTitle": str(scene.get("title", "")), "insertIndex": index,
                   "targetLineIds": [], "originalLines": [], "contiguous": True, "fixed": False}]
    else:
        selected = set(request.line_ids)
        found = {str(item["line"].get("id", "")) for item in timeline if str(item["line"].get("id", "")) in selected}
        if found != selected:
            raise HTTPException(status_code=404, detail="選択した発話行が見つかりません。")
        groups = []
        for scene in project.get("scenes", []):
            indexed = [(index, line) for index, line in enumerate(scene.get("lines", [])) if str(line.get("id", "")) in selected]
            if not indexed:
                continue
            indexes = [index for index, _line in indexed]
            contiguous = indexes == list(range(indexes[0], indexes[-1] + 1))
            groups.append({
                "id": deps.new_id("assistant_group"), "sceneId": str(scene.get("id", "")),
                "sceneTitle": str(scene.get("title", "")), "insertIndex": indexes[0],
                "targetLineIds": [str(line.get("id", "")) for _index, line in indexed],
                "originalLines": [dict(line) for _index, line in indexed], "contiguous": contiguous,
                "fixed": request.operation in {"paraphrase", "cast-compose"} or not contiguous,
            })
        validate_cast_composition_target(groups, request)
    variable = [group for group in groups if not group["fixed"]]
    if request.target_kind == "lines" and variable:
        targets = _allocate_line_targets(variable, request.target_line_count)
        for group, target in zip(variable, targets, strict=True):
            group["targetLineCount"] = target
    for group in groups:
        if group["fixed"]:
            group["targetLineCount"] = len(group["targetLineIds"])
        if request.target_kind == "minutes" and not group["fixed"]:
            weight = max(1, len(group["targetLineIds"]))
            total_weight = sum(max(1, len(item["targetLineIds"])) for item in variable)
            group["targetCharacters"] = max(80, round(request.target_minutes * 360 * request.speech_rate * weight / total_weight))
    return groups


def script_assistant_context(project: dict[str, Any], group: dict[str, Any]) -> dict[str, Any]:
    """Locate the edit and divide the script into chapter-distance bands.

    This function deliberately retains internal timeline rows. LLM payload
    projection and metadata removal belong to script_assistant_context_packing.
    """
    timeline = _timeline(project)
    target_ids = set(group["targetLineIds"])
    positions = [index for index, item in enumerate(timeline) if str(item["line"].get("id", "")) in target_ids]
    if positions:
        first, last = min(positions), max(positions)
    else:
        matching = [index for index, item in enumerate(timeline) if item["sceneId"] == group["sceneId"]]
        first = matching[group["insertIndex"]] if group["insertIndex"] < len(matching) else (matching[-1] + 1 if matching else len(timeline))
        last = first - 1
    prior = [item for item in timeline[:first] if item["line"].get("enabled") is not False]
    selected = [item for item in timeline if str(item["line"].get("id", "")) in target_ids]
    anchors = [item for item in timeline[first:last + 1]
               if str(item["line"].get("id", "")) not in target_ids and item["line"].get("enabled") is not False]
    following = [item for item in timeline[last + 1:] if item["line"].get("enabled") is not False][:3]
    recent = prior[-3:]
    before_near = prior[:-len(recent)] if recent else prior
    scene_count = len(project.get("scenes", []))
    virtual = scene_count == 1
    target_item = timeline[first] if first < len(timeline) else (timeline[first - 1] if first else None)
    target_chapter = _chapter_key(target_item, virtual=virtual) if target_item else ""
    distant: dict[str, list[dict[str, Any]]] = {}
    middle: list[dict[str, Any]] = []
    for item in before_near:
        key = _chapter_key(item, virtual=virtual)
        if key == target_chapter:
            middle.append(item)
        else:
            distant.setdefault(key, []).append(item)
    return {
        "projectId": str(project.get("id", "")), "targetChapter": target_chapter,
        "distantUnits": [
            {"id": key, "title": rows[0]["sceneTitle"], "rows": rows}
            for key, rows in distant.items()
        ],
        "middleRows": middle, "recentRows": recent, "selectedRows": selected,
        "anchorRows": anchors, "followingRows": following,
    }


deps.register(__name__, ["prepare_script_assistant_groups", "script_assistant_context", "script_assistant_signature"])

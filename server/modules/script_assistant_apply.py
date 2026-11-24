from __future__ import annotations

from pathlib import Path
from typing import Any

from server.app_deps import HTTPException
from server.registry import deps


def _take_paths(line: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    root = (deps.MEDIA_ROOT / "takes").resolve()
    for take in line.get("takes", []):
        url = str(take.get("audioUrl", ""))
        if not url.startswith("/media/"):
            continue
        path = (deps.MEDIA_ROOT / url.removeprefix("/media/")).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            continue
        paths.append(path)
    return paths


def _proposal_line(row: dict[str, Any], cue_ids: dict[str, str], *, line_id: str | None = None) -> dict[str, Any]:
    line = {
        "id": line_id or deps.new_id("line"), "characterId": row["characterId"], "text": row["text"],
        "stageDirection": row.get("stageDirection", ""), "takes": [], "selectedTakeId": None,
    }
    for key in ("speechRate", "gapSeconds"):
        if row.get(key) is not None:
            line[key] = row[key]
    proposal_cue = str(row.get("proposalCueId", ""))
    if proposal_cue:
        line["cueId"] = cue_ids.setdefault(proposal_cue, deps.new_id("cue"))
        line["startOffsetSeconds"] = row.get("startOffsetSeconds", 0.0)
    return line


def _chosen_group_rows(group: dict[str, Any], accepted_rows: set[str], accepted_groups: set[str]) -> list[dict[str, Any]]:
    if group["atomic"]:
        return group["rows"] if group["id"] in accepted_groups else []
    return [row for row in group["rows"] if row["id"] in accepted_rows]


def _apply_atomic_group(scene: dict[str, Any], group: dict[str, Any], chosen: list[dict[str, Any]],
                        cue_ids: dict[str, str]) -> list[Path]:
    target_ids = set(group["targetLineIds"])
    indexes = [index for index, line in enumerate(scene["lines"]) if str(line.get("id", "")) in target_ids]
    if not indexes:
        raise HTTPException(status_code=409, detail="置換対象が変更されています。再生成してください。")
    originals = [scene["lines"][index] for index in indexes]
    scene["lines"][indexes[0]:indexes[-1] + 1] = [_proposal_line(row, cue_ids) for row in chosen]
    return [path for line in originals for path in _take_paths(line)]


def _replace_fixed_row(line: dict[str, Any], row: dict[str, Any], cue_ids: dict[str, str],
                       *, preserve_cue: bool) -> list[Path]:
    remove_paths = _take_paths(line)
    enabled = line.get("enabled")
    cue = {key: line.get(key) for key in ("cueId", "startOffsetSeconds") if key in line} if preserve_cue else {}
    replacement = _proposal_line(row, cue_ids, line_id=str(line.get("id", "")))
    for key in ("textCfg", "voiceCfg", "captionCfg", "targetDurationSeconds"):
        if key in line:
            replacement[key] = line[key]
    replacement.update(cue)
    if enabled is not None:
        replacement["enabled"] = enabled
    line.clear()
    line.update(replacement)
    return remove_paths


def _apply_non_atomic_group(scene: dict[str, Any], group: dict[str, Any], chosen: list[dict[str, Any]],
                            cue_ids: dict[str, str], *, preserve_cue: bool) -> list[Path]:
    by_id = {str(line.get("id", "")): line for line in scene.get("lines", [])}
    remove_paths: list[Path] = []
    for row in chosen:
        original_id = str(row.get("originalLineId", ""))
        if not original_id:
            continue
        line = by_id.get(original_id)
        if line is None:
            raise HTTPException(status_code=409, detail="置換対象が変更されています。再生成してください。")
        remove_paths.extend(_replace_fixed_row(line, row, cue_ids, preserve_cue=preserve_cue))
    insert_rows = [row for row in chosen if not row.get("originalLineId")]
    if insert_rows:
        scene["lines"][group["insertIndex"]:group["insertIndex"]] = [_proposal_line(row, cue_ids) for row in insert_rows]
    return remove_paths


def apply_script_assistant_proposal(request: Any) -> dict[str, Any]:
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        proposal = deps.SCRIPT_ASSISTANT_PROPOSALS.get(request.proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="提案が見つかりません。再生成してください。")
    if request.source_signature != proposal["sourceSignature"]:
        raise HTTPException(status_code=409, detail="提案の元になった台本と一致しません。再生成してください。")
    assistant_request = deps.ScriptAssistantRequest.model_validate(proposal["request"])
    project = deps.read_project()
    if deps.script_assistant_signature(project, assistant_request) != proposal["sourceSignature"]:
        raise HTTPException(status_code=409, detail="生成後に台本が変更されています。再生成してください。")
    accepted_rows = set(request.accepted_row_ids)
    accepted_groups = set(request.accepted_group_ids)
    cue_ids: dict[str, str] = {}
    remove_paths: list[Path] = []
    changed = 0
    for group in proposal["groups"]:
        scene = next(item for item in project.get("scenes", []) if str(item.get("id", "")) == group["sceneId"])
        chosen = _chosen_group_rows(group, accepted_rows, accepted_groups)
        if not chosen:
            continue
        if group["atomic"]:
            remove_paths.extend(_apply_atomic_group(scene, group, chosen, cue_ids))
            changed += len(chosen)
            continue
        preserve_cue = assistant_request.operation in {"paraphrase", "cast-compose"} or not group["contiguous"]
        remove_paths.extend(_apply_non_atomic_group(scene, group, chosen, cue_ids, preserve_cue=preserve_cue))
        changed += len(chosen)
    if not changed:
        raise HTTPException(status_code=422, detail="採用する提案を選択してください。")
    deps.normalize_project_cues(project)
    deps.write_project(project)
    for path in remove_paths:
        path.unlink(missing_ok=True)
    with deps.SCRIPT_ASSISTANT_JOBS_LOCK:
        deps.SCRIPT_ASSISTANT_PROPOSALS.pop(request.proposal_id, None)
    return project


deps.register(__name__, ["apply_script_assistant_proposal"])

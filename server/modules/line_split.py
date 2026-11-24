"""Request model and atomic project mutation for splitting a dialogue line."""

from server.app_deps import Any, Field, HTTPException
from server.modules.request_model import StrictRequestModel
from server.registry import deps


class InsertLineRequest(StrictRequestModel):
    before_line_id: str = Field(default="", max_length=120)
    split_line_id: str = Field(default="", max_length=120)
    split_offset: int | None = Field(default=None, ge=0)


INHERITED_SPLIT_FIELDS = ("speechRate", "gapSeconds", "textCfg", "voiceCfg", "captionCfg")


def _split_pronunciations(values: Any, offset: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(values, list):
        return [], []
    before: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        start, end = item.get("start"), item.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if end <= offset:
            before.append(dict(item))
        elif start >= offset:
            after.append({**item, "start": start - offset, "end": end - offset})
    return before, after


def split_dialogue_line(scene: dict[str, Any], line_id: str, offset: int, new_line_id: str) -> dict[str, Any]:
    lines = scene.get("lines", [])
    source_index = next((index for index, line in enumerate(lines) if line.get("id") == line_id), -1)
    if source_index < 0:
        raise HTTPException(status_code=404, detail="Dialogue line not found.")
    source = lines[source_index]
    points = list(str(source.get("text", "")))
    if offset > len(points):
        raise HTTPException(status_code=422, detail="Split position is outside the dialogue text.")
    prefix, suffix = "".join(points[:offset]), "".join(points[offset:])
    before_readings, after_readings = _split_pronunciations(source.get("pronunciations"), offset)
    source["text"] = prefix
    source["pronunciations"] = before_readings
    source["selectedTakeId"] = None
    created = {
        "id": new_line_id,
        "characterId": str(source.get("characterId", "")),
        "text": suffix,
        "pronunciations": after_readings,
        "stageDirection": "",
        "takes": [],
        "selectedTakeId": None,
    }
    if offset < len(points):
        created.update({field: source[field] for field in INHERITED_SPLIT_FIELDS if field in source})
    insert_index = source_index + 1
    source_cue_id = str(source.get("cueId", ""))
    while source_cue_id and insert_index < len(lines) and str(lines[insert_index].get("cueId", "")) == source_cue_id:
        insert_index += 1
    lines.insert(insert_index, created)
    deps.normalize_scene_cues(scene)
    return created


deps.register(__name__, ["InsertLineRequest", "split_dialogue_line"])

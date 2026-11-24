from __future__ import annotations

from server.app_deps import json, re, Any, HTTPException
from server.registry import deps


def extract_json(content: str) -> dict[str, Any]:
    """Extract a JSON object even when a local model adds prose or a code fence.

    OpenAI-compatible local models do not all honour ``response_format``. In
    particular, some Qwen variants prepend a short explanation or ``<think>``
    block before returning the requested object. ``raw_decode`` lets us accept
    the first complete JSON object without trying to parse that surrounding
    text as JSON.
    """
    text = str(content or "").replace("\ufeff", "").strip()
    fenced = re.findall("```(?:json)?\\s*(.*?)\\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates = [*reversed(fenced), text]
    decoder = json.JSONDecoder()
    for candidate in candidates:
        candidate = candidate.strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
        objects: list[dict[str, Any]] = []
        consumed_until = 0
        for match in re.finditer("\\{", candidate):
            if match.start() < consumed_until:
                continue
            try:
                parsed, end = decoder.raw_decode(candidate, match.start())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                objects.append(parsed)
                consumed_until = end
        if objects:
            return objects[-1]
    raise HTTPException(status_code=502, detail="The LLM response did not contain a valid JSON object.")


def parse_character_profile_suggestion_text(
    content: str, *, labels: dict[str, str], cast_names: dict[str, str]
) -> dict[str, Any]:
    """Recover useful labelled suggestions from models that ignore JSON mode."""
    label_to_field = {label: field for field, label in labels.items()}
    details: dict[str, str] = {}
    relations: dict[str, dict[str, str]] = {}
    for source in str(content or "").replace("\r\n", "\n").split("\n"):
        line = re.sub("^\\s*(?:[-*•]|•|\\d+[.)])\\s*", "", source).strip()
        line = line.replace("**", "").replace("`", "")
        if not line or line.startswith(("```", "{", "}", "<think", "</think")):
            continue
        match = re.match("^(.+?)\\s*[:：]\\s*(.+?)\\s*$", line)
        if not match:
            continue
        label, value = match.groups()
        value = value.strip().strip("。")
        if not value or value in {"未設定", "なし", "不明", "省略"}:
            continue
        field = label_to_field.get(label) or (label if label in labels else None)
        if field:
            details[field] = value
            continue
        for cast_id, cast_name in cast_names.items():
            if label in {cast_name, f"{cast_name}との関係", f"{cast_name}との関係性"}:
                relations[cast_id] = {"note": value}
                break
    raw: dict[str, Any] = {}
    if details:
        raw["profile_details"] = details
    if relations:
        raw["cast_relations"] = relations
    return raw


def resolve_suggested_relation_id(
    raw_key: object, *, allowed_ids: set[str], other_casts: list[dict[str, Any]]
) -> str | None:
    """Resolve a profile-suggestion relation key without guessing same-name casts.

    Models commonly return the visible cast name even when asked for the
    internal id.  Accept that friendlier form, but only where it has one
    unambiguous matching blank relation target.
    """
    key = str(raw_key or "").strip()
    if key in allowed_ids:
        return key
    normalized_key = re.sub("\\s+", "", key)
    for suffix in ("との関係性", "との関係"):
        if normalized_key.endswith(suffix):
            normalized_key = normalized_key[: -len(suffix)]
            break
    matches = [
        item["id"]
        for item in other_casts
        if item["id"] in allowed_ids and re.sub("\\s+", "", item["name"]) == normalized_key
    ]
    return matches[0] if len(matches) == 1 else None


class DraftResponseFormatError(RuntimeError):
    """The model returned a draft-shaped response that cannot be trusted."""


class DraftStreamLoopError(RuntimeError):
    """Streaming was stopped after detecting a degenerate repeated response."""

    def __init__(self, reason: str, content: str) -> None:
        super().__init__(reason)
        self.content = content


class DraftModelCompatibilityError(RuntimeError):
    """The first dialogue response degenerated before a usable draft existed."""


def extract_complete_draft_json(content: str) -> dict[str, Any]:
    """Parse one complete top-level JSON object for a draft response.

    ``extract_json`` intentionally recovers the last object embedded in a
    loose response, which is useful for small suggestion endpoints.  A draft
    response is different: a malformed outer object may still contain valid
    nested line objects.  Treating one of those as the complete script loses
    nearly every line while appearing successful, so this parser never scans
    inside an invalid top-level draft object.
    """
    text = str(content or "").replace("\ufeff", "").strip()
    fenced = re.findall("```(?:json)?\\s*(.*?)\\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates = [*reversed(fenced), text]
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise DraftResponseFormatError("The LLM draft response was not one complete valid JSON object.")


def _apply_draft_line_metadata(value: str, current: dict[str, Any] | None) -> bool:
    if current is None:
        return False
    if value.startswith(">"):
        direction_text = re.sub(
            "^>\\s*(?:ト書き|演技(?:指示)?|指示|stage(?:_direction)?)?\\s*[:：]?\\s*", "", value
        ).strip()
        if direction_text:
            current["stage_direction"] = direction_text
        return True
    if value.startswith("@"):
        rate = re.search("(?:speech_rate|話速)\\s*[:=：]\\s*(-?\\d+(?:\\.\\d+)?)", value, re.IGNORECASE)
        gap = re.search("(?:gap_seconds|発話間隔)\\s*[:=：]\\s*(-?\\d+(?:\\.\\d+)?)", value, re.IGNORECASE)
        if rate:
            current["speech_rate"] = rate.group(1)
        if gap:
            current["gap_seconds"] = gap.group(1)
        return True
    direction = re.match("^(?:ト書き|演技(?:指示)?|指示|stage(?:_direction)?)\\s*[:：]\\s*(.+)$", value, re.IGNORECASE)
    if not direction:
        return False
    current["stage_direction"] = direction.group(1).strip()
    return True


def _match_draft_dialogue_line(value: str):
    patterns = (
        ("^[【\\[]\\s*([^】\\]]{1,48}?)\\s*[】\\]]\\s*(.+)$", 0),
        (
            "^(?:話者|speaker|character|キャラクター)\\s*[:：]\\s*([^:：]+?)\\s*[:：]\\s*(.+)$",
            re.IGNORECASE,
        ),
        ("^([^:：]{1,48}?)\\s*[:：]\\s*(.+)$", 0),
        ("^([^「『]{1,48}?)\\s*[「『](.+)[」』]\\s*$", 0),
    )
    for pattern, flags in patterns:
        if matched := re.match(pattern, value, flags):
            return matched
    return None


def extract_draft_response(content: str) -> dict[str, Any]:
    """Return a draft-shaped payload from JSON *or* conventional script text.

    JSON mode makes well-behaved endpoints more reliable, but it is not a
    prerequisite for writing a usable script.  This fallback deliberately
    understands the small set of formats models commonly produce when they
    ignore a structured-output request: ``話者: 台詞``, ``【話者】台詞``, and
    a following ``ト書き: ...`` line.  Speaker names are resolved to saved
    character IDs later by :func:`normalize_draft_scenes`.
    """
    text = str(content or "").replace("\ufeff", "").strip()
    json_attempt = bool(re.match("^(?:```(?:json)?\\s*)?\\{", text, re.IGNORECASE))
    if json_attempt:
        return extract_complete_draft_json(text)
    lines: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for source in text.replace("\r\n", "\n").split("\n"):
        value = re.sub("^\\s*(?:[-*•]|\\d+[.)])\\s*", "", source).strip()
        if not value or value.startswith("```") or value.startswith("<think") or value.startswith("</think"):
            continue
        if _apply_draft_line_metadata(value, current):
            continue
        matched = _match_draft_dialogue_line(value)
        if not matched:
            continue
        speaker, text = (part.strip() for part in matched.groups())
        if speaker.lower() in {"title", "タイトル", "scene", "シーン", "出力形式", "format"} or not text:
            continue
        current = {"speaker": speaker, "text": text.strip("「」『』 ")}
        lines.append(current)
    if lines:
        return {"scenes": [{"title": "Scene", "lines": lines}]}
    raise DraftResponseFormatError("The LLM response did not contain readable script lines.")


def draft_performance_validation_error(raw: dict[str, Any]) -> str:
    """Require the LLM to author every acting value; the app only validates it."""
    raw_scenes = raw.get("scenes", [])
    if not isinstance(raw_scenes, list):
        return "発話行の構造がありません。"
    checked = 0
    for scene in raw_scenes:
        if not isinstance(scene, dict) or not isinstance(scene.get("lines"), list):
            continue
        for line in scene["lines"]:
            if not isinstance(line, dict):
                continue
            checked += 1
            direction = str(
                line.get("stage_direction")
                or line.get("stageDirection")
                or line.get("direction")
                or line.get("stage_note")
                or ""
            ).strip()
            if not direction:
                return f"発話{checked}のト書きがありません。"
            try:
                speech_rate = float(line.get("speech_rate"))
                gap_seconds = float(line.get("gap_seconds"))
            except (TypeError, ValueError):
                return f"発話{checked}の話速または発話間隔がありません。"
            if not deps.LINE_SPEECH_RATE_MIN <= speech_rate <= deps.LINE_SPEECH_RATE_MAX:
                return f"発話{checked}の話速{speech_rate:g}が演技指定範囲{deps.LINE_SPEECH_RATE_MIN:.2f}〜{deps.LINE_SPEECH_RATE_MAX:.2f}の外です。"
            if not 0 <= gap_seconds <= 9999:
                return f"発話{checked}の発話間隔{gap_seconds:g}秒が不正です。"
    return "" if checked else "有効な発話行がありません。"


def strip_draft_emojis(value: str) -> str:
    """Remove both supported annotations and arbitrary emoji from LLM-authored prose."""
    text = str(value)
    result: list[str] = []
    index = 0
    supported = sorted(deps.IRODORI_EMOJIS, key=len, reverse=True)
    while index < len(text):
        match = next((emoji for emoji in supported if text.startswith(emoji, index)), None)
        if match:
            index += len(match)
        elif deps.is_emoji_component(text[index]):
            index += 1
        else:
            result.append(text[index])
            index += 1
    return "".join(result)


def retain_supported_draft_emojis(value: object, *, allowed: set[str] | None = None) -> str:
    """Keep only permitted Irodori-TTS emoji when text supplies them directly."""
    return deps.filter_llm_proposed_emojis(value, allowed=allowed)


def apply_emoji_annotations(text_value: object, annotations_value: object, *, enabled: bool) -> str:
    """Apply validated annotations to emoji-free spoken text."""
    return deps.apply_llm_emoji_annotations(text_value, annotations_value, enabled=enabled)


deps.register(
    __name__,
    [
        "DraftModelCompatibilityError",
        "DraftResponseFormatError",
        "DraftStreamLoopError",
        "apply_emoji_annotations",
        "draft_performance_validation_error",
        "extract_complete_draft_json",
        "extract_draft_response",
        "extract_json",
        "parse_character_profile_suggestion_text",
        "resolve_suggested_relation_id",
        "retain_supported_draft_emojis",
        "strip_draft_emojis",
    ],
)

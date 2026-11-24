"""Deterministic recovery for the small line protocols used by LLM helpers."""

from __future__ import annotations

from server.app_deps import json, re, Any
from server.modules.llm_transport_wrappers import unwrap_harmony_final
from server.registry import deps


def _text(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\ufeff", "").strip()
    text = unwrap_harmony_final(text)
    fenced = re.fullmatch(r"```(?:json|text|markdown)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    return fenced.group(1).strip() if fenced else text


def _json_or_text(value: object, key: str | None = None) -> str:
    text = _text(value)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return text
    if key and isinstance(parsed, dict) and isinstance(parsed.get(key), str):
        return _text(parsed[key])
    if isinstance(parsed, list) and all(isinstance(item, str) for item in parsed):
        return "\n".join(parsed)
    return text


def _lines(value: object, key: str | None = None) -> list[str]:
    bullet = r"(?:[-*•・]|[0-9０-９]+[.)．、]|[（(][0-9０-９]+[）)])\s*"
    return [
        re.sub(rf"^\s*{bullet}", "", line).strip().replace("**", "")
        for line in _json_or_text(value, key).splitlines()
        if line.strip()
    ]


def _accepted_tts_caption(value: object) -> str:
    caption = deps.strip_draft_emojis(str(value or "")).strip()
    return "" if deps.prohibited_negative_tts_caption_reason(caption) else caption


def normalize_suggested_theme(raw: object) -> str | None:
    """Remove transport wrappers without rewriting the model's creative brief."""
    text = _text(raw)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, str):
        text = _text(parsed)
    elif isinstance(parsed, dict):
        for key in ("theme", "proposal", "content"):
            value = parsed.get(key)
            if isinstance(value, str):
                text = _text(value)
                break
    return text.strip() or None


def parse_instruction(raw: object) -> str | None:
    text = _text(raw)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, str):
        return parsed.strip() or None
    if isinstance(parsed, dict) and isinstance(parsed.get("instruction"), str):
        return parsed["instruction"].strip() or None
    lines = _lines(raw, "instruction")
    tagged = {
        line.split("|", 1)[1].strip()
        for line in lines
        if line.startswith("INSTRUCTION|") and line.split("|", 1)[1].strip()
    }
    if len(tagged) == 1:
        return next(iter(tagged))
    return lines[0] if len(lines) == 1 and "|" not in lines[0] else None


def parse_voice_design(raw: object) -> dict[str, str] | None:
    return deps.parse_voice_design_response(raw, text=_text, lines=_lines)


def parse_line_annotations(value: str) -> list[dict[str, str]] | None:
    if not value or value == "NONE":
        return []
    annotations: list[dict[str, str]] = []
    for item in re.split(r"[;|]", value):
        emoji, separator, placement = item.strip().partition("@")
        if not separator or emoji not in deps.IRODORI_EMOJIS:
            continue
        if placement == "start":
            annotations.append({"emoji": emoji, "placement": "line_start"})
        elif placement == "end":
            annotations.append({"emoji": emoji, "placement": "line_end"})
        elif placement.startswith("before:") and placement[7:].strip():
            annotations.append({"emoji": emoji, "placement": "before_phrase", "target": placement[7:].strip()})
        # Annotation failures never make dialogue text unusable.  Discard a
        # malformed item rather than asking the model to repeat the response.
    return annotations


def _generated_line_protocol_rows(raw: object) -> list[str]:
    """Join only a uniquely identifiable numeric continuation of a LINE row."""
    rows: list[str] = []
    continuation = re.compile(r"^\|\s*-?\d+(?:\.\d+)?\s*\|\s*-?\d+(?:\.\d+)?\s*\|")
    for row in _lines(raw):
        if rows and rows[-1].startswith("LINE|") and continuation.match(row):
            rows[-1] += row
        else:
            rows.append(row)
    return rows
def _json_generated_lines(parsed: object) -> list[dict[str, Any]] | None:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("lines"), list):
        return None
    converted = []
    for item in parsed["lines"]:
        if not isinstance(item, dict):
            continue
        annotations = item.get("emoji_annotations", [])
        if not isinstance(annotations, list):
            annotations = []
        text_value = deps.strip_draft_emojis(str(item.get("text", ""))).strip()
        if text_value:
            converted.append({
                "text": text_value, "stage_direction": _accepted_tts_caption(item.get("stage_direction")),
                "speech_rate": item.get("speech_rate"), "gap_seconds": item.get("gap_seconds"),
                "emoji_annotations": annotations,
            })
    return list({json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in converted}.values()) or None
def parse_generated_lines(raw: object) -> list[dict[str, Any]] | None:
    text = _text(raw)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    json_lines = _json_generated_lines(parsed)
    if json_lines is not None:
        return json_lines
    result: list[dict[str, Any]] = []
    for line in _generated_line_protocol_rows(raw):
        canonical = deps.parse_canonical_direction_record(line, prefix="LINE")
        if canonical:
            result.append(canonical)
            continue
        # Keep an accidental final-field `|` from shifting preceding columns.
        parts = [part.strip() for part in line.split("|", 5)]
        if len(parts) == 5:
            # Small local models often omit the literal LINE marker while
            # retaining the five uniquely typed payload columns.
            parts = ["LINE", *parts]
        elif len(parts) == 6 and parts[0] != "LINE":
            preview_text = deps.strip_draft_emojis(parts[0]).strip()
            if parts[0] != parts[1] and preview_text == parts[1]:
                parts = ["LINE", *parts[1:]]
        if len(parts) != 6 or parts[0] != "LINE" or not all(parts[1:5]):
            continue
        line_text = deps.strip_draft_emojis(parts[1]).strip()
        if not line_text:
            continue
        try:
            rate, gap = float(parts[3]), float(parts[4])
        except ValueError:
            continue
        annotations = parse_line_annotations(parts[5])
        if annotations is None:
            return None
        annotations = [
            annotation
            for annotation in annotations
            if (
                (annotation["placement"] != "line_end" or annotation["emoji"] in deps.TAIL_EVENT_EMOJIS)
                and (annotation["placement"] != "before_phrase" or annotation.get("target", "") in line_text)
            )
        ]
        result.append(
            {
                "text": line_text,
                "stage_direction": _accepted_tts_caption(parts[2]),
                "speech_rate": rate,
                "gap_seconds": gap,
                "emoji_annotations": annotations,
            }
        )
    return list({json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in result}.values()) or None


deps.register(
    __name__,
    [
        "normalize_suggested_theme",
        "parse_generated_lines",
        "parse_instruction",
        "parse_line_annotations",
        "parse_voice_design",
    ],
)

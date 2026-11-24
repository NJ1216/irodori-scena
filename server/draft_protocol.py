from __future__ import annotations

import re
from typing import Any, Iterable

from server.modules.direction_fields import (
    parse_direction_values,
    recover_inline_emoji_anchor,
    recover_leaked_json_direction,
)
from server.plan_protocol_variants import normalize_plan_lines

def _clean_lines(content: str) -> Iterable[str]:
    normalized = str(content or "").replace("\r\n", "\n")
    # Some local models serialize requested record separators as the two
    # literal characters ``\\n``. Recover only when the following text is an
    # unmistakable compact-protocol record, leaving ordinary dialogue intact.
    normalized = re.sub(
        r"\\n(?=\s*(?:(?:NORMAL|SIM:[^|]*)\s*\||[A-Z]{1,3}\s*(?:\||:|：)|::(?:LINE|END|PERFORMANCE|TRANSITION)))",
        "\n",
        normalized,
    )
    for source in normalized.split("\n"):
        value = source.strip()
        if not value or value.startswith("```") or value.startswith("<think") or value.startswith("</think"):
            continue
        yield value


def _field(value: str) -> tuple[str, str] | None:
    matched = re.match(r"^([A-Z_]+)\s*(?:\||:|：)\s*(.*)$", value)
    if not matched:
        return None
    return matched.group(1).upper(), matched.group(2).strip()


def parse_context_selection(
    content: str, *, allowed_cast_ids: set[str], allowed_fields: set[str]
) -> dict[str, set[str]]:
    """Parse optional-field requests keyed by a short, request-local cast alias.

    ``allowed_cast_ids`` keeps its historical name for callers, but values can
    now be aliases such as ``A``.  The legacy ``NEED|cast|field`` form remains
    readable while the preferred form is the smaller ``A|field``.
    """
    selected: dict[str, set[str]] = {cast_id: set() for cast_id in allowed_cast_ids}
    for value in _clean_lines(content):
        matched = re.match(r"^NEED\s*(?:\||:)\s*([^|:\s]+)\s*(?:\||:)\s*([A-Za-z][A-Za-z0-9_]*)$", value)
        if not matched:
            matched = re.match(r"^([^|:\s]+)\s*(?:\||:|：)\s*([A-Za-z][A-Za-z0-9_]*)$", value)
        if not matched:
            continue
        cast_id, field = matched.groups()
        if cast_id in allowed_cast_ids and field in allowed_fields:
            selected[cast_id].add(field)
    return selected


def parse_plan_protocol(content: str) -> dict[str, Any]:
    result: dict[str, Any] = {"title": "", "story_bible": "", "cast_contexts": {}, "chapters": []}
    current: dict[str, Any] | None = None
    story_parts: list[str] = []
    collecting_unlabelled_beats = False

    def finish_current() -> None:
        nonlocal current, collecting_unlabelled_beats
        if current is not None:
            result["chapters"].append(current)
            current = None
        collecting_unlabelled_beats = False

    for value in normalize_plan_lines(_clean_lines(content)):
        cast_context = re.match(
            r"^CAST_CONTEXT\s*(?:\||:|：)\s*([^|:：]+)\s*(?:\||:|：)\s*([^|:：]*)\s*(?:\||:|：)\s*(.+)$",
            value,
        )
        if cast_context and current is None:
            alias, role, description = (item.strip() for item in cast_context.groups())
            if alias and description and alias not in result["cast_contexts"]:
                result["cast_contexts"][alias] = {"role": role, "description": description}
            continue
        chapter = re.match(r"^(?:::)?CHAPTER\s*(?:\||:|：)\s*(?:(\d+)\s*(?:\||:|：)\s*)?(.*)$", value)
        if chapter:
            finish_current()
            current = {
                "title": chapter.group(2).strip(),
                "objective": "",
                "beats": [],
                "supplement_beats": [],
                "opening_state": "",
                "closing_state": "",
                "novelty_requirement": "",
                "continuity_requirements": [],
                "speaking_casts": [],
                "mentioned_casts": [],
                "required_profile_fields": {},
            }
            continue
        if value in {"END_CHAPTER", "::END_CHAPTER", "::END"}:
            finish_current()
            continue
        parsed = _field(value)
        if not parsed:
            # Some local models label only the first BEAT row and then emit the
            # remaining requested beats as plain lines.  Once a BEAT section
            # has explicitly started, retain those lines until the next known
            # protocol field instead of regenerating an otherwise good plan.
            if current is not None and collecting_unlabelled_beats:
                beat = re.sub(r"^(?:[-*・]\s*|\d+[.)）]\s*)", "", value).strip()
                if beat:
                    current["beats"].append(beat)
            continue
        key, payload = parsed
        if current is None:
            if key == "TITLE" and not result["title"]:
                result["title"] = payload
            elif key in {"STORY", "STORY_BIBLE"} and payload:
                story_parts.append(payload)
            continue
        collecting_unlabelled_beats = key == "BEAT"
        if key == "TITLE":
            current["title"] = payload
        elif key == "OBJECTIVE":
            current["objective"] = payload
        elif key == "OPENING":
            current["opening_state"] = payload
        elif key == "BEAT" and payload:
            current["beats"].append(payload)
        elif key in {"EXPANSION", "SUPPLEMENT"} and payload:
            destination = "supplement_beats" if key == "SUPPLEMENT" else "beats"
            current[destination].append(payload)
        elif key == "CLOSING":
            current["closing_state"] = payload
        elif key == "NOVELTY":
            current["novelty_requirement"] = payload
        elif key in {"CONTINUITY", "RULE"} and payload:
            current["continuity_requirements"].append(payload)
        elif key in {"SPEAKING_CAST", "CAST"} and payload:
            alias = payload.split("|", 1)[0].strip()
            if alias and alias not in current["speaking_casts"]:
                current["speaking_casts"].append(alias)
        elif key in {"MENTIONED_CAST", "REFERENCE_CAST"} and payload:
            alias = payload.split("|", 1)[0].strip()
            if alias and alias not in current["mentioned_casts"]:
                current["mentioned_casts"].append(alias)
        elif key in {"REQUIRED_PROFILE", "CONTEXT"} and payload:
            parts = [part.strip() for part in payload.split("|", 1)]
            if len(parts) == 2 and parts[0] and parts[1]:
                fields = current["required_profile_fields"].setdefault(parts[0], [])
                if parts[1] not in fields:
                    fields.append(parts[1])
    finish_current()
    result["story_bible"] = " ".join(story_parts).strip()
    return result


def parse_dialogue_protocol(
    content: str,
    *,
    allowed_speakers: set[str] | None = None,
    speaker_aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Parse the compact ``A|台詞`` protocol and salvage common variants.

    Long application IDs never need to be emitted by the model.  Legacy
    three-line records remain supported so existing debug fixtures and older
    providers do not become unreadable.
    """
    lines: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    auto_number = 1

    def dialogue_payload(payload: str, *, recover_unseparated_emoji: bool = False) -> tuple[str, dict[str, str], bool]:
        text, separator, direction_payload = payload.partition("||")
        values = parse_direction_values(direction_payload) if separator else {}
        text, values = recover_leaked_json_direction(text.strip(), values)
        if separator or recover_unseparated_emoji:
            text, values = recover_inline_emoji_anchor(text, values)
        return text, values, bool(separator or values)

    def canonical_speaker(value: str) -> str | None:
        if speaker_aliases is not None:
            if value in speaker_aliases:
                return speaker_aliases[value]
            aliases = set(speaker_aliases.values())
            if len(aliases) == 1 and re.fullmatch(r"[A-Z]{1,3}", value):
                return next(iter(aliases))
        if allowed_speakers is None or value in allowed_speakers:
            return value
        return None

    def finish_current() -> None:
        nonlocal current, auto_number
        if current is not None and str(current.get("text", "")).strip():
            if not current.get("line_id"):
                current["line_id"] = f"L{auto_number:03d}"
            lines.append({**current, "line_id": str(current["line_id"])})
            auto_number += 1
        current = None

    for value in _clean_lines(content):
        typed = re.match(r"^(NORMAL|SIM:[^|]*)\s*\|\s*([^|\s]+)\s*\|\s*(.+)$", value)
        if typed:
            mode, speaker_value, raw_payload = typed.groups()
            speaker = canonical_speaker(speaker_value)
            if speaker is not None:
                finish_current()
                payload = re.sub(r"\|?\s*::END\s*$", "", raw_payload).strip()
                text, values, attempted = dialogue_payload(payload, recover_unseparated_emoji=True)
                if text:
                    if re.fullmatch(r"SIM:[A-Za-z0-9_-]{1,24}", mode):
                        values.setdefault("cue", mode)
                    line = {"line_id": f"L{auto_number:03d}", "character_id": speaker, "text": text}
                    if attempted:
                        line["integrated_direction_attempted"] = True
                    if values:
                        line["integrated_direction"] = values
                        line["integrated_direction_source_text"] = text
                    lines.append(line)
                    auto_number += 1
                continue
        scoped = re.match(
            r"^[Cc](\d+)\s*\|\s*([A-Za-z0-9_.-]{1,32})\s*\|\s*([A-Z]{1,3})\s*\|\s*(.+)$",
            value,
        )
        if scoped:
            speaker = canonical_speaker(scoped.group(3))
            if speaker is not None:
                finish_current()
                payload = re.sub(r"\|?\s*::END\s*$", "", scoped.group(4)).strip()
                text, values, attempted = dialogue_payload(payload)
                if text:
                    line = {"line_id": f"L{auto_number:03d}", "development_id": scoped.group(2),
                            "source_chapter_id": f"C{scoped.group(1)}", "character_id": speaker,
                            "text": text}
                    if attempted:
                        line["integrated_direction_attempted"] = True
                        if values:
                            line["integrated_direction"] = values
                            line["integrated_direction_source_text"] = text
                    lines.append(line)
                    auto_number += 1
                continue
        developed = re.match(r"^([A-Za-z0-9_.-]{1,32})\s*\|\s*([A-Z]{1,3})\s*\|\s*(.+)$", value)
        if developed:
            speaker = canonical_speaker(developed.group(2))
            if speaker is not None:
                finish_current()
                payload = re.sub(r"\|?\s*::END\s*$", "", developed.group(3)).strip()
                text, values, attempted = dialogue_payload(payload)
                if text:
                    line = {"line_id": f"L{auto_number:03d}", "development_id": developed.group(1),
                            "character_id": speaker, "text": text}
                    if attempted:
                        line["integrated_direction_attempted"] = True
                        if values:
                            line["integrated_direction"] = values
                            line["integrated_direction_source_text"] = text
                    lines.append(line)
                    auto_number += 1
                continue
        compact_sim = re.match(r"^([A-Z]{1,3})\s*\|\s*SIM:([^|]*)\|\s*(.+)$", value)
        if compact_sim:
            speaker = canonical_speaker(compact_sim.group(1))
            if speaker is not None:
                finish_current()
                text = re.sub(r"\|?\s*::END\s*$", "", compact_sim.group(3)).strip()
                if text:
                    lines.append({
                        "line_id": f"L{auto_number:03d}",
                        "character_id": speaker,
                        "text": text,
                    })
                    marker = compact_sim.group(2).strip()
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", marker):
                        lines[-1]["simultaneous_marker"] = marker
                    auto_number += 1
                continue
        compact = re.match(r"^([A-Z]{1,3})\s*(?:\||:|：)\s*(.+)$", value)
        if not compact and (allowed_speakers is not None or speaker_aliases is not None):
            compact = re.match(r"^([^|:：\s]+)\s*(?:\||:|：)\s*(.+)$", value)
        speaker = canonical_speaker(compact.group(1)) if compact else None
        if compact and speaker is not None:
            finish_current()
            payload = re.sub(r"\|?\s*::END\s*$", "", compact.group(2)).strip()
            text, values, attempted = dialogue_payload(payload)
            if text:
                line = {"line_id": f"L{auto_number:03d}", "character_id": speaker, "text": text}
                if attempted:
                    line["integrated_direction_attempted"] = True
                    if values:
                        line["integrated_direction"] = values
                        line["integrated_direction_source_text"] = text
                lines.append(line)
                auto_number += 1
            continue
        compact_header = re.match(
            r"^::LINE[_\s-]?([A-Z]{1,3})(?:\s*(?:\||:|：)\s*|\s+)?(.*)$",
            value,
        )
        speaker = canonical_speaker(compact_header.group(1)) if compact_header else None
        if compact_header and speaker is not None:
            finish_current()
            current = {
                "line_id": f"L{auto_number:03d}",
                "character_id": speaker,
                "text": compact_header.group(2).strip(),
            }
            continue
        record = re.match(r"^::LINE\s+([^\s]+)(?:\s+([^\s]+))?$", value)
        if record:
            finish_current()
            first, second = record.groups()
            current = {
                "line_id": first if second else f"L{auto_number:03d}",
                "character_id": second or first,
                "text": "",
            }
            continue
        bare_header = re.match(r"^::(character_[A-Za-z0-9_-]+|[A-Z]{1,3})$", value)
        speaker = canonical_speaker(bare_header.group(1)) if bare_header else None
        if bare_header and speaker is not None:
            finish_current()
            current = {
                "line_id": f"L{auto_number:03d}",
                "character_id": speaker,
                "text": "",
            }
            continue
        if value in {"::END", "END_LINE"}:
            finish_current()
            continue
        bracket = re.match(r"^[【\[]\s*([^】\]]{1,120}?)\s*[】\]]\s*(.+)$", value)
        if bracket:
            finish_current()
            current = {
                "line_id": f"L{auto_number:03d}",
                "character_id": bracket.group(1).strip(),
                "text": bracket.group(2).strip(),
            }
            continue
        parsed = _field(value)
        if current is not None and parsed and parsed[0] in {"TEXT", "DIALOGUE"}:
            payload = parsed[1]
            inline_end = bool(re.search(r"\|?\s*::END\s*$", payload))
            current["text"] = re.sub(r"\|?\s*::END\s*$", "", payload).strip()
            if inline_end:
                finish_current()
    finish_current()

    # Dialogue IDs are hints only. The application assigns immutable IDs after
    # validation, so repeated model IDs must not silently discard otherwise
    # salvageable text.
    for index, line in enumerate(lines):
        if line.get("integrated_direction_attempted") is True:
            line["integrated_direction_origin"] = f"R{index + 1}"
            line["integrated_direction_next_origin"] = f"R{index + 2}" if index + 1 < len(lines) else "END"
    return {"title": "Scene", "lines": lines}


def parse_performance_protocol(content: str) -> dict[str, Any]:
    performances: dict[str, dict[str, Any]] = {}
    transitions: dict[str, dict[str, Any]] = {}
    current_kind = ""
    current_key = ""
    current: dict[str, Any] | None = None

    def finish_current() -> None:
        nonlocal current_kind, current_key, current
        if current is None or not current_key:
            current_kind = ""
            current_key = ""
            current = None
            return
        if current_kind == "performance":
            performances[current_key] = current
        elif current_kind == "transition":
            transitions[current_key] = current
        current_kind = ""
        current_key = ""
        current = None

    for value in _clean_lines(content):
        # Preferred compact form.  The application already knows which line
        # follows L1/L2/etc., so the model only chooses the gap after this line.
        compact = re.match(
            r"^(L\d+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*([^|]+)\s*\|\s*(.*)$",
            value,
        )
        if compact:
            finish_current()
            line_id, speech_rate, gap_seconds, direction, performed_text = compact.groups()
            performances[line_id] = {
                "line_id": line_id,
                "performed_text": performed_text.strip(),
                "stage_direction": direction.strip(),
                "speech_rate": speech_rate.strip(),
            }
            transitions[f"{line_id}->NEXT"] = {
                "from_line_id": line_id,
                "to_line_id": "NEXT",
                "gap_seconds": gap_seconds.strip(),
                "intent": direction.strip(),
            }
            continue
        performance = re.match(r"^::PERFORMANCE\s+([^\s]+)$", value)
        if performance:
            finish_current()
            current_kind = "performance"
            current_key = performance.group(1)
            current = {"line_id": current_key}
            continue
        transition = re.match(r"^::TRANSITION\s+([^\s]+)\s+([^\s]+)$", value)
        if transition:
            finish_current()
            current_kind = "transition"
            current_key = f"{transition.group(1)}->{transition.group(2)}"
            current = {"from_line_id": transition.group(1), "to_line_id": transition.group(2)}
            continue
        if value in {"::END", "END_PERFORMANCE", "END_TRANSITION"}:
            finish_current()
            continue
        parsed = _field(value)
        if current is None or not parsed:
            continue
        key, payload = parsed
        if current_kind == "performance":
            if key in {"PERFORMED_TEXT", "TEXT"}:
                current["performed_text"] = payload
            elif key in {"DIRECTION", "STAGE_DIRECTION"}:
                current["stage_direction"] = payload
            elif key == "SPEECH_RATE":
                current["speech_rate"] = payload
        elif current_kind == "transition":
            if key == "GAP_SECONDS":
                current["gap_seconds"] = payload
            elif key in {"INTENT", "DIRECTION"}:
                current["intent"] = payload
    finish_current()
    return {"performances": performances, "transitions": transitions}

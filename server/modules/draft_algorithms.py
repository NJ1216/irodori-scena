from __future__ import annotations

from server.app_deps import difflib, math, re, unicodedata, Any
from server.registry import deps


def normalize_line_speech_rate(value: Any, default: float) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        rate = default
    return round(max(deps.LINE_SPEECH_RATE_MIN, min(deps.LINE_SPEECH_RATE_MAX, rate)), 2)


def normalize_line_gap(value: Any, default: float) -> float:
    try:
        gap = float(value)
    except (TypeError, ValueError):
        gap = default
    return round(max(0, min(9999, gap)), 2)


def normalize_draft_scenes(
    raw: dict[str, Any],
    permitted: set[str],
    default_speech_rate: float = 1.2,
    default_line_gap: float = 0.7,
    character_name_to_id: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []
    raw_scenes = raw.get("scenes", [])
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raw_lines = raw.get("lines", [])
        if isinstance(raw_lines, list) and raw_lines:
            raw_scenes = [{"title": raw.get("title", "Scene"), "lines": raw_lines}]
        elif isinstance(raw.get("scene"), dict):
            raw_scenes = [raw["scene"]]
        elif any((key in raw for key in ("text", "dialogue", "content", "line"))):
            raw_scenes = [{"title": raw.get("title", "Scene"), "lines": [raw]}]
        else:
            raw_scenes = []
    names = character_name_to_id or {}
    for raw_scene in raw_scenes:
        if not isinstance(raw_scene, dict):
            continue
        lines = []
        raw_lines = raw_scene.get("lines", [])
        if not isinstance(raw_lines, list):
            continue
        for raw_line in raw_lines:
            if not isinstance(raw_line, dict):
                continue
            character_id = str(
                raw_line.get("character_id")
                or raw_line.get("characterId")
                or raw_line.get("speaker_id")
                or raw_line.get("speakerId")
                or ""
            ).strip()
            if character_id not in permitted:
                speaker_name = str(
                    raw_line.get("character_name")
                    or raw_line.get("speaker")
                    or raw_line.get("character")
                    or character_id
                    or ""
                ).strip()
                character_id = names.get(speaker_name, speaker_name if speaker_name in permitted else character_id)
            if character_id not in permitted and len(permitted) == 1:
                character_id = next(iter(permitted))
            text = deps.apply_emoji_annotations(
                raw_line.get("text")
                or raw_line.get("dialogue")
                or raw_line.get("content")
                or raw_line.get("line")
                or "",
                raw_line.get("emoji_annotations"),
                enabled=True,
            )
            direction = deps.strip_draft_emojis(
                str(
                    raw_line.get("stage_direction")
                    or raw_line.get("stageDirection")
                    or raw_line.get("direction")
                    or raw_line.get("stage_note")
                    or ""
                )
            ).strip()
            if text and (not direction):
                direction = "自然に話す。"
            if character_id in permitted and text:
                lines.append(
                    {
                        "id": deps.new_id("line"),
                        "characterId": character_id,
                        "text": text,
                        "stageDirection": direction,
                        "speechRate": normalize_line_speech_rate(raw_line.get("speech_rate"), default_speech_rate),
                        "gapSeconds": normalize_line_gap(raw_line.get("gap_seconds"), default_line_gap),
                        "takes": [],
                        "selectedTakeId": None,
                    }
                )
        if lines:
            scenes.append(
                {
                    "id": deps.new_id("scene"),
                    "title": str(raw_scene.get("title", "Scene")).strip() or "Scene",
                    "lines": lines,
                }
            )
    return scenes


def spoken_character_count(scenes: list[dict[str, Any]]) -> int:
    return sum((len(str(line.get("text", ""))) for scene in scenes for line in scene["lines"]))


def has_excessive_draft_repetition(scenes: list[dict[str, Any]]) -> bool:
    """Reject one long filler loop without penalising ordinary dramatic pauses.

    Punctuation remains valid Irodori-TTS input and is never removed from an
    accepted line.  It is ignored *only* for this quality gate so a model
    cannot satisfy a length target by repeating the same short phrase behind
    different comma or ellipsis spacing.
    """
    for scene in scenes:
        for line in scene.get("lines", []):
            normalized = re.sub(
                "[^\\wぁ-んァ-ヶ一-龠々ー]", "", unicodedata.normalize("NFKC", str(line.get("text", "")))
            )
            if len(normalized) < 120:
                continue
            maximum_unit = min(24, len(normalized) // 5)
            for unit_length in range(4, maximum_unit + 1):
                repeated = re.search(f"(.{{{unit_length}}})\\1{{4,}}", normalized)
                if repeated and len(repeated.group(0)) >= max(80, len(normalized) * 0.35):
                    return True
    return False


def safe_draft_chapter_characters(token_budget: int) -> int:
    """Maximum spoken-text target representable by the available output tokens."""
    return max(
        deps.MIN_DRAFT_CHUNK_CHARACTERS,
        min(
            deps.MAX_DRAFT_CHUNK_CHARACTERS,
            math.floor((token_budget - deps.DRAFT_DIALOGUE_TOKEN_OVERHEAD) / 2.2),
        ),
    )


def draft_dialogue_signature(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    return re.sub("[^\\wぁ-んァ-ヶ一-龠々ー]", "", normalized)


def is_repeated_draft_dialogue(signature: str, prior_signatures: list[str]) -> bool:
    if len(signature) < 12:
        return False
    for prior in prior_signatures:
        if signature == prior:
            return True
        if len(prior) < 12 or abs(len(signature) - len(prior)) > max(len(signature), len(prior)) * 0.35:
            continue
        if difflib.SequenceMatcher(a=signature, b=prior, autojunk=False).ratio() >= 0.9:
            return True
    return False


def remove_repeated_draft_scenes(
    scenes: list[dict[str, Any]], prior_texts: list[str]
) -> tuple[list[dict[str, Any]], int]:
    """Keep new dialogue only; short acknowledgements may naturally repeat."""
    signatures = [draft_dialogue_signature(text) for text in prior_texts]
    filtered: list[dict[str, Any]] = []
    discarded = 0
    for scene in scenes:
        lines: list[dict[str, Any]] = []
        for line in scene.get("lines", []):
            signature = draft_dialogue_signature(str(line.get("text", "")))
            if is_repeated_draft_dialogue(signature, signatures):
                discarded += 1
                continue
            lines.append(line)
            if signature:
                signatures.append(signature)
        if lines:
            filtered.append({**scene, "lines": lines})
    return (filtered, discarded)


def compact_draft_continuity(
    chapter: dict[str, Any], raw: dict[str, Any], scenes: list[dict[str, Any]], character_names: dict[str, str]
) -> str:
    """Carry forward a factual digest plus a tiny concrete anchor for the next call."""
    summary = re.sub("\\s+", " ", str(raw.get("continuity_summary", "")).strip())
    if not summary:
        summary = "この章で描いた出来事と登場人物の反応を引き継ぐ。"
    summary = summary[:600]
    recent: list[str] = []
    for scene in scenes:
        for line in scene.get("lines", []):
            text = str(line.get("text", "")).strip()
            if text:
                name = character_names.get(str(line.get("characterId", "")), "キャスト")
                recent.append(f"{name}: {text[:100]}")
    anchor = " / ".join(recent[-3:])[:260]
    closing = str(chapter.get("closing_state", "")).strip()
    parts = [f"直前章「{str(chapter.get('title', ''))}」の確定記録:", summary]
    if closing:
        parts.append(f"次章への引き継ぎ: {closing}")
    if anchor:
        parts.append(f"直近の具体的発話: {anchor}")
    return "\n".join(parts)[: deps.DRAFT_CONTINUITY_MAX_CHARS]


def remove_repeated_draft_dialogue(dialogue: dict[str, Any], prior_texts: list[str]) -> tuple[dict[str, Any], int]:
    signatures = [draft_dialogue_signature(text) for text in prior_texts]
    lines: list[dict[str, Any]] = []
    discarded = 0
    for line in dialogue.get("lines", []):
        text = str(line.get("text", ""))
        signature = draft_dialogue_signature(text)
        values = line.get("integrated_direction")
        prior_line = lines[-1] if lines else None
        prior_values = prior_line.get("integrated_direction") if isinstance(prior_line, dict) else None
        marker = str(values.get("cue", "")).strip() if isinstance(values, dict) else ""
        prior_marker = str(prior_values.get("cue", "")).strip() if isinstance(prior_values, dict) else ""
        intentional_cue_repeat = bool(
            prior_line
            and marker == prior_marker
            and re.fullmatch(r"SIM:[A-Za-z0-9_-]{1,32}", marker)
            and str(line.get("character_id", "")) != str(prior_line.get("character_id", ""))
            and signature == draft_dialogue_signature(str(prior_line.get("text", "")))
        )
        if is_repeated_draft_dialogue(signature, signatures) and not intentional_cue_repeat:
            discarded += 1
            continue
        lines.append(line)
        if signature:
            signatures.append(signature)
    return ({**dialogue, "lines": lines}, discarded)


def _draft_block_signature(line: dict[str, Any]) -> str:
    return f"{str(line.get('character_id', ''))}\x1f{draft_dialogue_signature(str(line.get('text', '')))}"


def _largest_repeated_draft_block(lines: list[dict[str, Any]], candidate_start: int) -> tuple[int, int] | None:
    """Find the later side of one substantial, non-overlapping repeated block."""
    signatures = [_draft_block_signature(line) for line in lines]
    best: tuple[int, int] | None = None
    for earlier in range(len(lines)):
        for later in range(max(candidate_start, earlier + 3), len(lines)):
            if signatures[earlier] != signatures[later]:
                continue
            length = 0
            while (
                earlier + length < later
                and later + length < len(lines)
                and signatures[earlier + length] == signatures[later + length]
            ):
                length += 1
            if length < 3:
                continue
            characters = sum((len(draft_dialogue_signature(str(line.get("text", "")))) for line in lines[later : later + length]))
            if characters < 30:
                continue
            if best is None or length > best[1]:
                best = (later, length)
    return best


def remove_repeated_draft_blocks(
    dialogue: dict[str, Any], prior_lines: list[dict[str, Any]]
) -> tuple[dict[str, Any], int]:
    """Drop only later copies of substantial dialogue blocks.

    Single short acknowledgements remain untouched.  Earlier accepted dialogue
    is read-only; when a new response repeats its tail, only the new copy is
    removed.
    """
    candidate_lines = list(dialogue.get("lines", []))
    discarded = 0
    while True:
        combined = [*prior_lines, *candidate_lines]
        repeated = _largest_repeated_draft_block(combined, len(prior_lines))
        if repeated is None:
            break
        start, length = repeated
        candidate_offset = start - len(prior_lines)
        del candidate_lines[candidate_offset : candidate_offset + length]
        discarded += length
    return ({**dialogue, "lines": candidate_lines}, discarded)


def resequence_draft_dialogue(dialogue: dict[str, Any], chapter_index: int) -> None:
    """Assign contiguous IDs after all acceptance filters have run."""
    for number, line in enumerate(dialogue.get("lines", []), start=1):
        line["line_id"] = f"C{chapter_index + 1:03d}L{number:03d}"


def draft_dialogue_simplified_glyphs(dialogue: dict[str, Any]) -> set[str]:
    return {
        character
        for line in dialogue.get("lines", [])
        for character in str(line.get("text", ""))
        if character in deps.DISALLOWED_SIMPLIFIED_CHINESE
    }


def repair_only_replaces_simplified_glyphs(source: str, repaired: str) -> bool:
    """Allow a repair to change only the known invalid glyph positions."""
    if len(source) != len(repaired):
        return False
    return all(
        (
            before == after
            or (before in deps.DISALLOWED_SIMPLIFIED_CHINESE and after not in deps.DISALLOWED_SIMPLIFIED_CHINESE)
            for before, after in zip(source, repaired)
        )
    )


def draft_dialogue_spoken_by_cast(dialogue: dict[str, Any]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for line in dialogue.get("lines", []):
        cast_id = str(line.get("character_id", ""))
        totals[cast_id] = totals.get(cast_id, 0) + len(str(line.get("text", "")))
    return totals


def draft_cast_priority_by_id(cast_context: list[dict[str, Any]], cast_alias_by_id: dict[str, str]) -> dict[str, str]:
    cast_id_by_alias = {alias: cast_id for cast_id, alias in cast_alias_by_id.items()}
    priorities: dict[str, str] = {}
    for cast in cast_context:
        cast_id = cast_id_by_alias.get(str(cast.get("cast", "")))
        preference = cast.get("preferences", {})
        priority = str(preference.get("priority", "standard")) if isinstance(preference, dict) else "standard"
        if cast_id:
            priorities[cast_id] = priority if priority in {"main", "supporting", "standard"} else "standard"
    return priorities


def draft_priority_is_satisfied(dialogue: dict[str, Any], priority_by_cast_id: dict[str, str]) -> bool:
    ranks = {"standard": 0, "supporting": 1, "main": 2}
    totals = draft_dialogue_spoken_by_cast(dialogue)
    for higher_id, higher_priority in priority_by_cast_id.items():
        for lower_id, lower_priority in priority_by_cast_id.items():
            if ranks.get(higher_priority, 0) <= ranks.get(lower_priority, 0):
                continue
            if totals.get(higher_id, 0) <= totals.get(lower_id, 0):
                return False
    return True


def spoken_dialogue_count(dialogue: dict[str, Any]) -> int:
    return sum((len(str(line.get("text", ""))) for line in dialogue.get("lines", [])))


def limit_draft_dialogue_characters(dialogue: dict[str, Any], maximum: int) -> dict[str, Any]:
    """Keep whole lines near the remaining target without accepting runaway output."""
    total = 0
    lines: list[dict[str, Any]] = []
    for line in dialogue.get("lines", []):
        length = len(str(line.get("text", "")))
        if total + length > maximum:
            if not lines and length <= maximum + 160:
                lines.append(line)
            break
        lines.append(line)
        total += length
    return {**dialogue, "lines": lines}


def dialogue_has_semantic_content(dialogue: dict[str, Any]) -> bool:
    return any((len(draft_dialogue_signature(str(line.get("text", "")))) >= 2 for line in dialogue.get("lines", [])))


def compact_dialogue_continuity(
    chapter: dict[str, Any], dialogue: dict[str, Any], character_names: dict[str, str]
) -> str:
    recent = []
    for line in dialogue.get("lines", [])[-3:]:
        name = character_names.get(str(line.get("character_id", "")), "キャスト")
        recent.append(f"{name}: {str(line.get('text', ''))[:120]}")
    parts = [
        f"直前章「{str(chapter.get('title', ''))}」の目的: {str(chapter.get('objective', ''))}",
        f"確定した終了状態: {str(chapter.get('closing_state', ''))}",
        "直近の確定台詞: " + " / ".join(recent),
    ]
    return "\n".join(parts)[: deps.DRAFT_CONTINUITY_MAX_CHARS]


def compact_performance_state(scenes: list[dict[str, Any]], character_names: dict[str, str]) -> str:
    records: list[str] = []
    for scene in scenes:
        for line in scene.get("lines", []):
            records.append(
                f"{character_names.get(str(line.get('characterId', '')), 'キャスト')}: {str(line.get('text', ''))[:80]} / {str(line.get('stageDirection', ''))[:80]} / rate={line.get('speechRate')} / gap={line.get('gapSeconds')}"
            )
    return "\n".join(records[-3:])[:600]


deps.register(
    __name__,
    [
        "compact_dialogue_continuity",
        "compact_draft_continuity",
        "compact_performance_state",
        "dialogue_has_semantic_content",
        "draft_cast_priority_by_id",
        "draft_dialogue_signature",
        "draft_dialogue_simplified_glyphs",
        "draft_dialogue_spoken_by_cast",
        "draft_priority_is_satisfied",
        "has_excessive_draft_repetition",
        "is_repeated_draft_dialogue",
        "normalize_draft_scenes",
        "normalize_line_gap",
        "normalize_line_speech_rate",
        "remove_repeated_draft_dialogue",
        "remove_repeated_draft_blocks",
        "remove_repeated_draft_scenes",
        "repair_only_replaces_simplified_glyphs",
        "resequence_draft_dialogue",
        "safe_draft_chapter_characters",
        "spoken_character_count",
        "spoken_dialogue_count", "limit_draft_dialogue_characters",
    ],
)

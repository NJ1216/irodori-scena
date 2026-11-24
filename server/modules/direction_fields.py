from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Any

from server.registry import deps


FIELD_SEPARATOR = re.compile(r"(?:\|+|;)(?=(?:emoji|rate|gap|direction|cue)=)")
JSON_DIRECTION_KEY = re.compile(
    r'(?P<boundary>[,、}\])））」』"「『]+)\s*'
    r'(?P<key>emoji|rate|gap|direction|cue)(?:["」』])?\s*:'
)
CUE_MARKER = re.compile(r"^SIM:[A-Za-z0-9_-]{1,24}$")
CURRENT_INTERRUPTION = re.compile(r"割り込|食い気味|畳み掛|被せ|かぶせ|遮る|遮って|言葉を挟")
REVERB_EMOJI = "📢"
REVERB_INTENT = re.compile(r"エコー|リバーブ|残響")
REVERB_NEGATION = re.compile(
    r"(?:エコー|リバーブ|残響)(?:を)?(?:使わない|かけない|掛けない|避ける|なし|不要|禁止)"
)


@dataclass(frozen=True)
class PerformanceDirectionPolicy:
    emoji: bool
    speech_rate: bool
    gap: bool
    direction: bool
    cue: bool
    negative_gap: bool
    overwrite_existing: bool
    allowed_emojis: frozenset[str]
    speech_rate_min: float
    speech_rate_max: float
    gap_min: float
    gap_max: float
    emoji_enabled_by_cast: dict[str, bool]


def performance_direction_policy(request: Any) -> PerformanceDirectionPolicy:
    """Normalize draft, direction, and line-assistant settings into one contract."""
    if hasattr(request, "performance_speech_rate_min"):
        cast_policy = {
            cast_id: emoji_enabled_for_cast(request, cast_id) for cast_id in request.character_ids
        }
        speech_rate = gap = direction = True
        cue = bool(request.simultaneous_cues)
        negative_gap = bool(request.overlapping_speech)
        overwrite = True
        rate_min, rate_max = request.performance_speech_rate_min, request.performance_speech_rate_max
        gap_min, gap_max = request.performance_gap_min, request.performance_gap_max
        allowed = request.allowed_emojis
    elif hasattr(request, "line_ids"):
        cast_policy = {
            cast_id: emoji_enabled_for_cast(request, cast_id)
            for cast_id in getattr(request, "cast_settings", {})
        }
        speech_rate = bool(request.speech_rate)
        gap = bool(request.gap_seconds)
        direction = bool(request.stage_direction)
        cue = bool(getattr(request, "allow_negative_gap", False))
        negative_gap = cue
        overwrite = bool(request.overwrite_existing)
        rate_min, rate_max = request.speech_rate_min, request.speech_rate_max
        gap_min, gap_max = request.gap_min, request.gap_max
        allowed = request.allowed_emojis
    else:
        cast_policy = {str(request.character_id): bool(request.emoji_expressions)}
        speech_rate = gap = direction = True
        cue = False
        negative_gap = False
        overwrite = True
        rate_min, rate_max = deps.LINE_SPEECH_RATE_MIN, deps.LINE_SPEECH_RATE_MAX
        gap_min, gap_max = 0.0, 5.0
        allowed = deps.IRODORI_EMOJIS
    emoji = bool(request.emoji_expressions) or any(cast_policy.values())
    return PerformanceDirectionPolicy(
        emoji=emoji,
        speech_rate=speech_rate,
        gap=gap,
        direction=direction,
        cue=cue,
        negative_gap=negative_gap,
        overwrite_existing=overwrite,
        allowed_emojis=frozenset(ai_allowed_emojis(request, allowed)),
        speech_rate_min=rate_min,
        speech_rate_max=rate_max,
        gap_min=gap_min,
        gap_max=gap_max,
        emoji_enabled_by_cast=cast_policy,
    )


def explicit_reverb_request_text(request: Any) -> str:
    """Return only request-local author text that may authorize AI reverb."""
    if hasattr(request, "instruction"):
        return str(request.instruction)
    if hasattr(request, "keywords"):
        return f"{request.keywords}\n{getattr(request, 'character_context', '')}"
    if hasattr(request, "theme") and hasattr(request, "character_ids"):
        return str(request.theme)
    return ""


def ai_reverb_explicitly_requested(request: Any) -> bool:
    """Require an affirmative request-local acoustic instruction for AI-authored reverb."""
    text = re.sub(r"\s+", "", explicit_reverb_request_text(request))
    return bool(REVERB_INTENT.search(REVERB_NEGATION.sub("", text)))


def ai_allowed_emojis(request: Any, allowed: Any) -> set[str]:
    """Apply request-local AI policy without changing manual emoji support."""
    permitted = set(allowed).intersection(deps.AI_PROPOSABLE_EMOJIS)
    if not ai_reverb_explicitly_requested(request):
        permitted.discard(REVERB_EMOJI)
    return permitted


def performance_direction_prompt_rules(policy: PerformanceDirectionPolicy) -> str:
    allowed = "、".join(sorted(policy.allowed_emojis)) or "なし"
    negative_gap = (
        "gapの負値は、次行が先行行の終了前に始まる被せ・割り込みだけに使い、先行行へ設定する。"
        if policy.negative_gap else "gapに負値を書かない。"
    )
    cue = (
        "cueは異なるキャストの連続2〜8行の全文同時開始だけに同じSIM:S1形式を使う。"
        if policy.cue else "cueはNONEにする。"
    )
    emoji_rules = deps.EMOJI_PERFORMANCE_RULEBOOK if policy.emoji and policy.allowed_emojis else ""
    return (
        f"{emoji_rules}\n"
        "emojiは許可EMOJIから選び、`絵文字列@本文に完全一致する最短語句`形式で最大3個、"
        "複数候補は`;`で区切る。@の右側は必ずその行の日本語本文から一字一句そのまま複写する。"
        "`emoji=😆@楽しい`は正しいが、`emoji=😆@😆`、`emoji=😆@start`、本文にない語句は無効。"
        "本文やdirectionへ絵文字を書かない。EMOJI許可の行を一律NONEにせず、笑い、泣き、息、"
        "明確な感情・声色・速度感が音声として自然な行では独立AI演出と同じ基準で積極的に提案する。"
        "ただし件数合わせや全行への機械的付与はしない。"
        f"許可EMOJI: {allowed}。rateは{policy.speech_rate_min:.2f}〜{policy.speech_rate_max:.2f}、"
        f"gapは{policy.gap_min:.2f}〜{policy.gap_max:.2f}。directionは肯定形の簡潔な演技指示。"
        f"{negative_gap}{cue}各フィールドは独立して返し、不明ならNONEまたは省略する。"
    )


def emoji_enabled_for_cast(request: Any, character_id: str) -> bool:
    settings = getattr(request, "cast_settings", {})
    cast_setting = settings.get(character_id) if isinstance(settings, dict) else None
    return bool(cast_setting.emoji_expressions if cast_setting is not None else request.emoji_expressions)


def emoji_enabled_for_request(request: Any) -> bool:
    return any(emoji_enabled_for_cast(request, cast_id) for cast_id in request.character_ids)


def parse_direction_values(parts: list[str] | str) -> dict[str, str]:
    """Parse known fields independently; later duplicates never replace the first."""
    source = parts if isinstance(parts, list) else [parts]
    values: dict[str, str] = {}
    for part in source:
        for field in FIELD_SEPARATOR.split(part):
            key, separator, value = field.partition("=")
            key = key.strip()
            if separator and key in {"emoji", "rate", "gap", "direction", "cue"} and key not in values:
                values[key] = value.strip().rstrip("|").rstrip()
    return values


def recover_leaked_json_direction(text: str, values: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Detach an unmistakable JSON-field tail that leaked into spoken text."""
    matches = list(JSON_DIRECTION_KEY.finditer(text))
    if len({match.group("key") for match in matches}) < 2:
        return text, values
    start = matches[0].start()
    cleaned = text[:start].rstrip().rstrip(',、"」』）)]}').rstrip()
    if not cleaned:
        return text, values
    recovered = dict(values)
    for index, match in enumerate(matches):
        key = match.group("key")
        if key in recovered:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[match.end():end].strip().strip(',"「」『』').strip()
        if raw and raw.lower() != "null":
            recovered[key] = raw
    return cleaned, recovered


def parse_canonical_direction_record(line: str, *, prefix: str) -> dict[str, Any] | None:
    match = re.fullmatch(rf"{re.escape(prefix)}\|(.+?)\|\|(.+)", line)
    if not match:
        return None
    text, values = recover_inline_emoji_anchor(
        deps.strip_draft_emojis(match.group(1)).strip(), parse_direction_values(match.group(2))
    )
    return {"text": text, "direction_values": values} if text else None


def recover_inline_emoji_anchor(text: str, values: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Move a model-leaked trailing ``EMOJI@anchor`` annotation out of spoken text."""
    at = text.rfind("@")
    if at <= 0 or at == len(text) - 1:
        return text, values
    before, anchor = text[:at], text[at + 1:].strip()
    remaining = before
    reversed_emojis: list[str] = []
    catalog = sorted(deps.IRODORI_EMOJIS, key=len, reverse=True)
    while remaining:
        emoji = next((item for item in catalog if remaining.endswith(item)), None)
        if emoji is None:
            break
        reversed_emojis.append(emoji)
        remaining = remaining[:-len(emoji)]
    if not reversed_emojis:
        return text, values
    cleaned = remaining.rstrip()
    recovered = "".join(reversed(reversed_emojis)) + f"@{anchor}"
    result = dict(values)
    current = str(result.get("emoji", "")).strip()
    if "@" not in current and anchor in cleaned:
        result["emoji"] = recovered
    return cleaned, result


def direction_number(value: str, lower: float, upper: float, *, clamp: bool) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if clamp:
        return max(lower, min(upper, number))
    return number if lower <= number <= upper else None


def validated_direction_patch(
    request: Any,
    row: dict[str, Any],
    values: dict[str, str],
    allowed: set[str],
    *,
    character_id: str = "",
) -> dict[str, Any]:
    """Apply the shared AI-direction field rules without making completeness atomic."""
    policy = replace(performance_direction_policy(request), allowed_emojis=frozenset(allowed))
    patch = apply_performance_direction(policy, row, values, character_id=character_id)
    # Group-level callers validate cue completeness and adjacency separately.
    patch.pop("simultaneous_marker", None)
    return patch


def apply_performance_direction(
    policy: PerformanceDirectionPolicy,
    row: dict[str, Any],
    values: dict[str, str],
    *,
    character_id: str = "",
) -> dict[str, Any]:
    """Apply independently valid fields while leaving rejected siblings untouched."""
    patch: dict[str, Any] = {}
    emoji_allowed = policy.emoji and policy.emoji_enabled_by_cast.get(character_id, policy.emoji)
    proposal = values.get("emoji", "").strip()
    if emoji_allowed and proposal not in {"", "NONE"}:
        source = str(row["text"])
        directed = deps.apply_llm_emoji_anchor_proposals(source, proposal, set(policy.allowed_emojis))
        if directed is not None and directed != source:
            patch["text"] = directed
    for key, target, enabled, lower, upper in (
        ("rate", "speechRate", policy.speech_rate, policy.speech_rate_min, policy.speech_rate_max),
        ("gap", "gapSeconds", policy.gap, policy.gap_min, policy.gap_max),
    ):
        value = values.get(key, "").strip()
        if enabled and value:
            number = direction_number(value, lower, upper, clamp=key == "rate")
            if number is not None:
                patch[target] = number
    direction = deps.strip_draft_emojis(values.get("direction", "")).strip()
    if policy.direction and direction not in {"", "NONE"}:
        if deps.prohibited_negative_tts_caption_reason(direction) is None:
            patch["stageDirection"] = direction
    cue = values.get("cue", "").strip()
    if policy.cue and CUE_MARKER.fullmatch(cue):
        patch["simultaneous_marker"] = cue
    return patch


def normalize_negative_gap_ownership(
    records: list[tuple[dict[str, Any], dict[str, str]]], *, default_gap: float,
    following_row: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Move a current-line interruption offset onto the preceding stored edge."""
    normalized = [dict(values) for _row, values in records]
    for index in range(1, len(records)):
        row, _values = records[index]
        values = normalized[index]
        gap = direction_number(values.get("gap", ""), -30, 9999, clamp=False)
        acting = f"{values.get('direction', '')} {row.get('text', '')}"
        if gap is None or gap >= 0 or not CURRENT_INTERRUPTION.search(acting):
            continue
        normalized[index - 1]["gap"] = str(gap)
        existing = direction_number(str(row.get("gap", "")), 0, 9999, clamp=False)
        normalized[index]["gap"] = str(default_gap if existing is None else existing)
    # Apply after ownership correction: gap belongs to the edge to the next
    # spoken row, including a following chapter/chunk when one is available.
    following = [row for row, _values in records[1:]] + [following_row or {}]
    for (row, _values), values, next_row in zip(records, normalized, following):
        _normalize_same_speaker_gap(row, next_row, values)
    return normalized


def _normalize_same_speaker_gap(row, next_row, values) -> None:
    speaker = row.get("character_id")
    gap = direction_number(values.get("gap", ""), -30, 9999, clamp=False)
    if speaker and speaker == next_row.get("character_id") and gap is not None and gap < 0:
        values["gap"] = "0"


def usable_integrated_field_count(request: Any, line: dict[str, Any]) -> int:
    values = line.get("integrated_direction")
    if not isinstance(values, dict):
        return 0
    text = str(line.get("text", ""))
    count = 0
    allowed = ai_allowed_emojis(request, request.allowed_emojis)
    emoji = str(values.get("emoji", "")).strip()
    character_id = str(line.get("character_id", ""))
    if emoji_enabled_for_cast(request, character_id) and emoji not in {"", "NONE"}:
        count += deps.apply_llm_emoji_anchor_proposals(text, emoji, allowed) is not None
    rate = str(values.get("rate", "")).strip()
    if rate:
        count += direction_number(rate, request.performance_speech_rate_min, request.performance_speech_rate_max, clamp=True) is not None
    gap = str(values.get("gap", "")).strip()
    if gap:
        count += direction_number(gap, request.performance_gap_min, request.performance_gap_max, clamp=False) is not None
    direction = deps.strip_draft_emojis(str(values.get("direction", ""))).strip()
    if direction not in {"", "NONE"}:
        count += deps.prohibited_negative_tts_caption_reason(direction) is None
    cue = str(values.get("cue", "")).strip()
    if request.simultaneous_cues and CUE_MARKER.fullmatch(cue):
        count += 1
    return count


deps.register(__name__, [
    "CUE_MARKER", "PerformanceDirectionPolicy", "ai_allowed_emojis", "ai_reverb_explicitly_requested",
    "apply_performance_direction", "direction_number",
    "emoji_enabled_for_cast", "emoji_enabled_for_request", "normalize_negative_gap_ownership",
    "performance_direction_policy",
    "performance_direction_prompt_rules",
    "parse_canonical_direction_record", "parse_direction_values", "recover_inline_emoji_anchor",
    "recover_leaked_json_direction",
    "usable_integrated_field_count",
    "validated_direction_patch",
])

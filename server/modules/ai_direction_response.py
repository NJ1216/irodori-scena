from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from server.modules.direction_fields import emoji_enabled_for_cast
from server.registry import deps

def _parse(content: str) -> dict[str, list[str]]:
    records: dict[str, list[str]] = {}
    for raw in content.replace("\r", "").split("\n"):
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) >= 2 and parts[0].startswith("L") and parts[0][1:].isdigit():
            records[parts[0]] = parts[1:]
    return records
def _record_values(parts: list[str]) -> dict[str, str]:
    return deps.parse_direction_values(parts)


def _direction_contract(rows: list[dict[str, Any]]):
    aliases = [str(row["alias"]) for row in rows]
    nullable = {"type": ["string", "null"]}
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "line": {"type": "string", "enum": aliases}, "emoji": nullable, "rate": nullable,
        "gap": nullable, "direction": nullable, "cue": nullable,
    }, "required": ["line", "emoji", "rate", "gap", "direction", "cue"]}
    def legacy(content):
        return [{"line": alias, **deps.parse_direction_values(parts)} for alias, parts in _parse(content).items()]
    return deps.LlmRecordContract(
        "ai-direction", 1, schema, "line", frozenset(aliases),
        legacy_suffix="既定のL番号|項目名=値形式で返す。", legacy_parser=legacy,
    )


def _project_direction_records(records) -> str:
    return "\n".join(f"{row['line']}|" + "|".join(
        f"{key}={row[key]}" for key in ("emoji", "rate", "gap", "direction", "cue") if row.get(key) is not None
    ) for row in records)


def _response_token_limit(rows: list[dict[str, Any]]) -> int:
    source_characters = sum(len(str(row["text"])) + len(str(row["stage"])) for row in rows)
    return min(4096, max(384, 256 + source_characters + (len(rows) * 64)))
def _direction_number(value: str, lower: float, upper: float, *, clamp: bool) -> float | None:
    return deps.direction_number(value, lower, upper, clamp=clamp)


def _enforce_patch_tutting(patch: dict[str, Any], row: dict[str, Any]) -> None:
    if "text" not in patch:
        return
    direction = str(patch.get("stageDirection", row.get("stage", "")))
    patch["text"] = deps.enforce_tutting_intent(str(patch["text"]), direction)


def _directed_emoji_text(
    request: deps.AiDirectionRequest,
    source: str,
    emoji_value: str,
    allowed: set[str],
) -> str | None:
    has_existing_emoji = deps.strip_irodori_expression_emojis(source) != source
    if request.overwrite_existing:
        source = deps.strip_irodori_expression_emojis(source)
    if has_existing_emoji and not request.overwrite_existing:
        return source
    if not emoji_value:
        return source
    return deps.apply_llm_emoji_anchor_proposals(source, emoji_value, allowed)


def _performance_patch(
    request: deps.AiDirectionRequest,
    row: dict[str, Any],
    values: dict[str, str],
    allowed: set[str],
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if request.emoji_expressions and emoji_enabled_for_cast(request, str(row.get("character_id", ""))):
        text = _directed_emoji_text(request, str(row["text"]), values.get("emoji", "").strip(), allowed)
        if text is not None and text != row["text"]:
            patch["text"] = text
    without_emoji = request.model_copy(update={"emoji_expressions": False})
    patch.update(deps.validated_direction_patch(without_emoji, row,
                                                {key: value for key, value in values.items() if key != "emoji"},
                                                allowed, character_id=str(row.get("character_id", ""))))
    _enforce_patch_tutting(patch, row)
    return patch


def _request_text(
    request: deps.AiDirectionRequest,
    rows: list[dict[str, Any]],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    cast_context: list[dict[str, Any]] | None = None,
    *,
    job_id: str,
    debug_response_path: Path,
    on_progress: Callable[[str], None] | None = None,
    benchmark_prompt_order: str = "cache-first",
    benchmark_seed: int | None = None,
    simultaneous_cues: bool = False,
) -> str:
    system, user = deps.build_direction_prompt(
        request,
        rows,
        before,
        after,
        cast_context,
        benchmark_prompt_order=benchmark_prompt_order,
    )
    if simultaneous_cues:
        system = system.replace(
            "Use only emoji, rate, gap, direction fields",
            "Use only emoji, rate, gap, direction, cue fields",
        )
        system += "\nAI台本専用の同時発話候補も同じ応答で判定する。明確な掛け声・一斉反応など、同時に始める連続2〜8行の各レコードへ `cue=SIM:S1` を追加する。台本が複数キャストの同時発話を説明・宣言し、その直後の連続行で実演している場合、該当する異なるキャストの各行にはcueを必ず付ける。同じ候補には同じ短いマーカーを使い、独白・内心には付けない。通常行にはcueフィールドを書かない。演技の他フィールドはcueの有無と独立して必ず提案する。"
    streamed_records = []
    def publish(records):
        streamed_records.extend(records)
        callback = on_progress or (lambda streamed: deps.update_draft_job(
            job_id, receivedCharacters=len(streamed), receivedRecords=len(_parse(streamed))))
        callback(_project_direction_records(streamed_records))
    result = deps.complete_records(
        request,
        contract=_direction_contract(rows),
        system=system,
        user=user,
        max_tokens=_response_token_limit(rows),
        stream=True,
        debug_response_path=debug_response_path,
        on_records=publish,
        should_cancel=lambda: deps.draft_cancel_requested(job_id),
        job_id=job_id,
        benchmark_seed=benchmark_seed,
    )
    return _project_direction_records(result.records)

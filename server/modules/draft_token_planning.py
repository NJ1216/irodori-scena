from __future__ import annotations

from server.app_deps import Any, math
from server.registry import deps


def max_draft_chunk_characters(
    output_tokens: int, *, max_characters: int = deps.MAX_DRAFT_CHUNK_CHARACTERS,
) -> int:
    maximum = deps.MIN_DRAFT_CHUNK_CHARACTERS
    for characters in range(deps.MIN_DRAFT_CHUNK_CHARACTERS, max_characters + 1):
        required = math.ceil(characters * 1.5) + (96 * math.ceil(characters / 80)) + 256
        if required > output_tokens:
            break
        maximum = characters
    return maximum


def draft_output_tokens_for_characters(characters: int) -> int:
    lines = max(1, math.ceil(max(0, characters) / 80))
    return max(deps.DRAFT_DIALOGUE_TOKEN_FLOOR, math.ceil(max(0, characters) * 1.5) + 96 * lines + 256)


def _candidate_cost(
    context: int, *, prompt_tokens: int, target_characters: int, output_tokens: int,
    max_characters: int,
) -> tuple[float, int, int, int]:
    usable_output = max(deps.DRAFT_DIALOGUE_TOKEN_FLOOR, min(
        output_tokens, context - prompt_tokens - deps.DRAFT_CONTEXT_SAFETY_MARGIN))
    chunk_characters = max_draft_chunk_characters(usable_output, max_characters=max_characters)
    calls = max(1, math.ceil(target_characters / chunk_characters))
    resent = max(0, calls - 1) * min(prompt_tokens, 1536)
    prefill = calls * (prompt_tokens + resent / max(1, calls)) * (1 + context / 65536)
    return prefill + target_characters * 1.9 + context / 32, calls, resent, usable_output


def select_draft_job_context(
    *, ceiling: int, prompt_tokens: int, target_characters: int, minimize_calls: bool = False,
    dynamic_output: bool = False, provider_output_ceiling: int | None = None,
) -> dict[str, Any]:
    tiers = (4096, 8192, 16384, 32768, 65536, 131072, 262144, 524288, 1048576)
    candidates = [tier for tier in tiers if tier <= ceiling] or [ceiling]
    max_characters = target_characters if dynamic_output else deps.MAX_DRAFT_CHUNK_CHARACTERS
    scored = []
    for context in candidates:
        available = context - prompt_tokens - deps.DRAFT_CONTEXT_SAFETY_MARGIN
        maximum = available if dynamic_output else min(deps.DRAFT_DIALOGUE_TOKEN_CEILING, available)
        if provider_output_ceiling:
            maximum = min(maximum, provider_output_ceiling)
        if maximum < deps.DRAFT_DIALOGUE_TOKEN_FLOOR:
            continue
        score = _candidate_cost(context, prompt_tokens=prompt_tokens,
            target_characters=target_characters, output_tokens=maximum, max_characters=max_characters)
        scored.append((score[0], context, *score[1:]))
    if not scored:
        raise RuntimeError("LLM要求がモデルカードのContext上限へ収まりません。Context上限を正しい値へ修正してください。")
    score, context, calls, resent, output = min(scored, key=(
        (lambda item: (item[2], item[1], item[0])) if minimize_calls else (lambda item: item[0])))
    return {"effectiveContext": context, "outputTokenLimit": output,
            "maxChunkCharacters": max_draft_chunk_characters(output, max_characters=max_characters),
            "predictedCalls": calls, "estimatedResentTokens": resent, "predictedCost": round(score, 2),
            "candidateCosts": [{"context": item[1], "cost": round(item[0], 2), "calls": item[2],
                "resentTokens": item[3]} for item in scored]}


deps.register(__name__, ["draft_output_tokens_for_characters", "max_draft_chunk_characters",
                         "select_draft_job_context"])

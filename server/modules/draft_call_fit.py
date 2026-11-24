"""Reduce new work, preserving author/cast context, before a dialogue send."""
from __future__ import annotations

import math

from server.registry import deps
from server.modules.ollama_context import DraftContextError


def fit_dialogue_request(request, system, user, requested, token_budget):
    profile = deps.active_draft_capability_profile() or {}
    context = profile.get("jobContext", profile.get("dialogueContext", profile.get("contextCeiling")))
    sections = user["sections"]
    packet = next(section["current_packet"] for section in sections if "current_packet" in section)
    final_sources = {chapter["beats"][-1].split("|", 1)[0] for chapter in packet
                     if chapter.get("final_conclusion") and chapter.get("beats")}
    targets = next(section["accepted_dialogue_and_current_request"] for section in sections
                   if "accepted_dialogue_and_current_request" in section)
    average_line = max(20, requested / max(1, targets["recommended_new_line_count"]))
    safe_tokens = token_budget
    for _ in range(4):
        input_tokens = deps.estimate_llm_input_tokens(system, user)
        if isinstance(context, int):
            safe_tokens = min(token_budget, context - input_tokens - deps.DRAFT_CONTEXT_SAFETY_MARGIN)
        if safe_tokens < output_reservation(80, average_line):
            raise DraftContextError(
                f"固定必須入力 {input_tokens} + 80文字分の出力予約 + 安全余白 "
                f"{deps.DRAFT_CONTEXT_SAFETY_MARGIN} tokenがContext {context} tokenへ収まりません。")
        capacity = min(requested, max(80, math.floor((safe_tokens - 416) / (1.7 + 64 / average_line))))
        sources = [str(beat).split("|", 1)[0] for chapter in packet for beat in chapter.get("beats", [])]
        if len(sources) > 1 and capacity < requested:
            # Drop the last requested scene; it stays untouched in the job queue.
            packet[-1] = {**packet[-1], "beats": packet[-1]["beats"][:-1]}
            if not packet[-1]["beats"]:
                packet.pop()
            for chapter in packet:
                chapter["final_conclusion"] = any(beat.split("|", 1)[0] in final_sources for beat in chapter["beats"])
            continue
        line_count = max(1, math.ceil(capacity / average_line))
        requested = capacity
        targets.update(target_new_spoken_characters=requested,
                       minimum_new_spoken_characters=math.floor(requested * .95),
                       maximum_new_spoken_characters=math.ceil(requested * 1.05),
                       recommended_new_line_count=line_count,
                       source_target_characters=deps.allocate_source_targets(
                           sources, requested, targets.get("source_target_characters", {})))
        targets["source_recommended_line_count"] = deps.allocate_source_targets(
            sources, line_count, targets["source_target_characters"])
        break
    return sources, requested, min(safe_tokens, output_reservation(requested, average_line))


def output_reservation(characters, average_line=30):
    """Reserve Japanese text plus per-row JSON and optional acting fields."""
    return math.ceil(characters * 1.7 + math.ceil(characters / average_line) * 64 + 352)

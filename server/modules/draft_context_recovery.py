from __future__ import annotations

from typing import Any
from server.registry import deps


def reduce_ollama_context(profile: dict[str, Any] | None, detail: str) -> bool:
    normalized = detail.casefold()
    if (
        profile
        and isinstance(profile.get("jobContext"), int)
        and any(marker in normalized for marker in ("context", "num_ctx", "memory", "メモリ"))
    ):
        # A pinned draft cannot resend the same request at a smaller allocation.
        profile["contextReplanRequired"] = True
        return False
    if (
        profile
        and "directionChunkSize" in profile
        and any(marker in normalized for marker in ("context", "num_ctx", "memory", "メモリ"))
    ):
        current_context = int(profile.get("effectiveContext") or 4096)
        lower_context = next((tier for tier in (16384, 8192, 4096) if tier < current_context), current_context)
        current_chunk = int(profile.get("directionChunkSize") or 30)
        lower_chunk = next((size for size in (20, 10, 5, 1) if size < current_chunk), current_chunk)
        if lower_context >= current_context and lower_chunk >= current_chunk:
            return False
        profile["effectiveContext"] = lower_context
        profile["contextCeiling"] = min(int(profile.get("contextCeiling") or lower_context), lower_context)
        profile["directionChunkSize"] = lower_chunk
        profile["retryDirectionChunk"] = True
        profile["fallbackReason"] = "；".join(
            filter(
                None,
                [
                    str(profile.get("fallbackReason", "")),
                    f"Context拒否またはメモリ不足のため{lower_context}・{lower_chunk}行へ縮小: {detail[-160:]}",
                ],
            )
        )
        # The caller must rebuild the prompt with the smaller chunk; do not
        # transparently resend the already-too-large request.
        return False
    if (
        not profile
        or profile.get("provider") not in {"ollama", "lmstudio", "scena-local"}
        or not any(marker in detail.casefold() for marker in ("num_ctx", "context", "memory", "メモリ"))
    ):
        return False
    current = int(profile.get("effectiveContext", 4096))
    lowered = max(4096, current // 2)
    if lowered >= current:
        return False
    profile["effectiveContext"] = lowered
    profile["outputTokenLimit"] = max(
        deps.DRAFT_DIALOGUE_TOKEN_FLOOR,
        lowered - int(profile.get("promptTokenEstimate", 0)) - deps.DRAFT_CONTEXT_SAFETY_MARGIN,
    )
    profile["maxChunkCharacters"] = deps.max_draft_chunk_characters(profile["outputTokenLimit"])
    profile["fallbackReason"] = "；".join(
        filter(None, [str(profile.get("fallbackReason", "")), f"num_ctx拒否のため{lowered}へ縮小: {detail[-160:]}"])
    )
    return True

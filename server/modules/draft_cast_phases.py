from __future__ import annotations

from typing import Any

from server.registry import deps


def draft_dialogue_cast_context(cast_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove plan-only introduction seeds before dialogue writing."""
    return [
        {
            key: value
            for key, value in cast.items()
            if key not in {"reader_facing_introduction_seed", "reader_facing_role_seed"}
        }
        for cast in cast_context
    ]


def draft_chapter_cast_context(
    cast_context: list[dict[str, Any]], chapter: dict[str, Any], _characters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Select chapter speakers and references without reducing their saved context."""
    by_alias = {str(item.get("cast", "")): item for item in cast_context}
    speakers = [str(value) for value in chapter.get("speaking_casts", []) if str(value) in by_alias]
    references = [str(value) for value in chapter.get("mentioned_casts", []) if str(value) in by_alias]
    effective_speakers = speakers or list(by_alias)
    selected = [*effective_speakers, *(alias for alias in references if alias not in effective_speakers)]
    character_by_alias = {
        str(item.get("cast", "")): character for item, character in zip(cast_context, _characters)
    }
    return [
        {
            **dict(by_alias[alias]),
            **({"profile": deps.draft_character_profile(
                character_by_alias[alias], set(deps.DRAFT_OPTIONAL_PROFILE_FIELDS),
            )} if "summary" not in by_alias[alias] else {}),
            "chapter_role": "speaker" if alias in effective_speakers else "reference",
        }
        for alias in selected
    ]


def draft_performance_cast_context(cast_context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only identity, delivery constraints, and relationships for acting."""
    result: list[dict[str, Any]] = []
    for cast in cast_context:
        if "summary" in cast:
            delivery: Any = {
                "exact_profile": cast.get("exact_profile", {}), "summary": cast.get("summary", ""),
            }
        else:
            labels = ("一人称:", "二人称:", "通常の呼び方:", "基本の敬称:",
                      "通常の呼び方の補足:", "性格:", "話し方:")
            delivery = "\n".join(line for line in str(cast.get("profile", "")).splitlines()
                                  if line.startswith(labels)) or "（追加の話し方設定なし）"
        item = {
            "cast": cast.get("cast", ""),
            "name": cast.get("name", ""),
            "delivery_constraints": delivery,
            "relations": cast.get("relations", []),
        }
        preferences = cast.get("preferences", {})
        if isinstance(preferences, dict) and preferences.get("emoji"):
            item["preferences"] = {"emoji": preferences["emoji"]}
        result.append(item)
    return result


deps.register(__name__, ["draft_chapter_cast_context", "draft_dialogue_cast_context", "draft_performance_cast_context"])

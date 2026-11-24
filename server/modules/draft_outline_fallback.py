from __future__ import annotations

from typing import Any

from server.registry import deps


def fallback_draft_chapter(request: Any, number: int, chapter_count: int) -> dict[str, Any]:
    phases = (
        ("導入", "状況と登場人物の当面の目的を具体的に示す。"),
        ("きっかけ", "新しい事実・提案・反応を一つ持ち込み、会話を動かす。"),
        ("掘り下げ", "相手の受け止め方を通じて、背景や本音を新しく明かす。"),
        ("転換", "これまでの会話から自然に導かれる判断または行動を選ぶ。"),
        ("決着", "最初の目的に答えを出し、感情の落ち着きどころを描く。"),
        ("余韻", "新しい約束・認識・次への含みを残して場面を閉じる。"),
    )
    phase_index = min(len(phases) - 1, (number - 1) * len(phases) // max(1, chapter_count))
    phase, objective = phases[phase_index]
    return {
        "title": f"第{number}部：{phase}",
        "objective": objective,
        "beats": [f"テーマ「{request.theme.strip() or '指定された場面'}」に関する、この章だけの具体的な出来事を起こす。"],
        "continuity_requirements": ["既出の事実、呼び方、人物同士の関係性を維持する。"],
        "opening_state": "前章までに確立した状況を受け取る。",
        "closing_state": "次章で扱う新しい論点または感情を一つ残す。",
        "novelty_requirement": "既出の会話を言い換えず、新しい出来事・情報・判断を必ず一つ入れる。",
    }


def fallback_story_chapters(
    request: Any, count: int, *, minimum_beats: int = 2,
) -> list[dict[str, Any]]:
    sections = deps.draft_theme_sections(request.theme)
    outline_policy = deps.draft_outline_policy(request.target_minutes, request.theme)
    buckets: list[list[dict[str, str]]] = [[] for _ in range(count)]
    for index, section in enumerate(sections):
        buckets[min(count - 1, index * count // len(sections))].append(section)
    chapters: list[dict[str, Any]] = []
    for index, bucket in enumerate(buckets):
        chapter = fallback_draft_chapter(request, index + 1, count)
        if bucket:
            chapter.update({"objective": bucket[0]["text"], "beats": [section["text"] for section in bucket],
                            "chapter_id": f"C{index + 1}",
                            "source_section_ids": [section["id"] for section in bucket]})
            author_title = next((section["title"] for section in bucket if section.get("title_source") == "author"), "")
            if author_title:
                chapter["title"] = author_title
        if outline_policy["mode"] == "expand" and len(sections) == 1:
            progression = [
                "テーマが今この場で始まる具体的なきっかけと、登場人物の当面の目的を示す。",
                "最初の反応を受けて新しい事実または本音を明かし、状況を一段進める。",
                "それまでと異なる判断または行動を起こし、人物の感情や関係を変化させる。",
                "テーマの目的へ答えを出し、既出内容を繰り返さず場面を着地させる。",
            ]
            chapter["beats"] = progression[:max(2, min(len(progression), minimum_beats))]
        chapters.append(chapter)
    chapters[-1]["closing_state"] = "作者条件とそれまでの進行を踏まえ、自然に締めくくる。"
    return chapters


deps.register(__name__, ["fallback_draft_chapter", "fallback_story_chapters"])

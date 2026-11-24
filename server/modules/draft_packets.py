from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from server.registry import deps
from server.modules.partial_json import extract_source_lines
from server.modules import draft_schedule


@dataclass(frozen=True)
class DraftBeat:
    source: str
    chapter_index: int
    text: str
    target_characters: int


def _allocated(total: int, count: int) -> list[int]:
    if count <= 0:
        return []
    return [total // count + (1 if index < total % count else 0) for index in range(count)]


def planned_draft_beats(
    chapters: list[dict[str, Any]], target: int, *, source_capacity: int | None = None, short_framing: bool = False,
) -> list[DraftBeat]:
    """Assign stable ownership IDs without splitting a story beat by length.

    Capacity is a packet-packing concern. If a beat is too large, planning must
    produce additional semantic beats with their own state transition.
    """
    capacity = draft_schedule.development_capacity(source_capacity or 600)
    desired = draft_schedule.required_developments(target, capacity=capacity)
    existing = sum(max(1, len([item for item in chapter.get("beats", []) if str(item).strip()]))
                   for chapter in chapters)
    extras = max(0, desired - existing)
    phases = ("開始状態を具体化する", "関係と状況を深化させる", "新しい事実で転換する", "選択を確定する")
    expanded: list[list[str]] = []
    for chapter_index, chapter in enumerate(chapters):
        texts = [str(item).strip() for item in chapter.get("beats", []) if str(item).strip()]
        if not texts:
            texts = [str(chapter.get("objective", "章の目的")).strip() or "章の目的を会話で進める。"]
        share = extras // len(chapters) + int(chapter_index < extras % len(chapters))
        for offset in range(share):
            texts.append(
                f"技術スロット{offset + 1}: {phases[offset % len(phases)]}。"
                f"開始: 直前の終了状態 / 進展: {chapter.get('objective', '')} / 終了: 次の状態へ移る"
            )
        expanded.append(texts)
    sources: list[tuple[int, str, str]] = []
    for chapter_index, chapter in enumerate(chapters):
        texts = expanded[chapter_index]
        sources.extend((chapter_index, f"D{chapter_index + 1}.{beat_index + 1}", text)
                       for beat_index, text in enumerate(texts))
        ending = chapter.get("author_ending")
        if isinstance(ending, dict) and str(ending.get("text", "")).strip():
            prompt = (f"{str(ending['text']).strip()} "
                      "この状態を実際に成立させて場面を閉じる。予告や言及だけで完了扱いにしない。")
            owner_index, owner, final_beat = sources[-1]
            sources[-1] = (owner_index, owner, f"{final_beat} / 必須終了条件: {prompt}")
            ending["id"] = owner
    allocations = _allocated(target, len(sources))
    if short_framing and len(sources) >= 3 and target >= 960:
        intro = min(320, max(160, target // 12))
        ending = min(600, max(400, target // 12))
        allocations = [intro, *_allocated(target - intro - ending, len(sources) - 2), ending]
    if len(sources) > 1 and target >= 320:
        allocations[0] = max(160, allocations[0])
        allocations[-1] = max(160, allocations[-1])
        excess = sum(allocations) - target
        for index in range(len(allocations) - 2, 0, -1):
            reduction = min(excess, allocations[index])
            allocations[index] -= reduction
            excess -= reduction
            if not excess:
                break
    result: list[DraftBeat] = []
    for (chapter_index, source, text), beat_target in zip(sources, allocations):
        if source == "AUTHOR_ENDING":
            result.append(DraftBeat(source, chapter_index, text, beat_target))
            continue
        else:
            result.append(DraftBeat(source, chapter_index, text, beat_target))
    return result


def build_draft_packets(beats: list[DraftBeat], *, capacity: int = 5000) -> list[list[DraftBeat]]:
    """Pack consecutive chapters, splitting only at beat boundaries."""
    packets: list[list[DraftBeat]] = []
    current: list[DraftBeat] = []
    current_size = 0
    for beat in beats:
        size = max(1, beat.target_characters)
        if current and current_size + size > capacity:
            packets.append(current)
            current, current_size = [], 0
        current.append(beat)
        current_size += size
    if current:
        packets.append(current)
    return packets


def packet_chapters(packet: list[DraftBeat], chapters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, list[DraftBeat]] = {}
    for beat in packet:
        grouped.setdefault(beat.chapter_index, []).append(beat)
    return [{**chapters[index], "number": index + 1,
             "beats": [f"{beat.source}|{beat.text}" for beat in grouped[index]],
             "target_characters": sum(beat.target_characters for beat in grouped[index])}
            for index in sorted(grouped)]


def allocate_source_targets(source_ids: list[str], total: int,
                            planned_targets: dict[str, int]) -> dict[str, int]:
    """Allocate the exact call target using the plan's source proportions."""
    weights = [max(0, int(planned_targets.get(source, 0))) for source in source_ids]
    if not source_ids:
        return {}
    if not sum(weights):
        weights = [1] * len(source_ids)
    raw = [max(0, total) * weight / sum(weights) for weight in weights]
    allocated = [int(value) for value in raw]
    remainder = max(0, total) - sum(allocated)
    order = sorted(range(len(source_ids)), key=lambda index: (raw[index] - allocated[index], -index), reverse=True)
    for index in order[:remainder]:
        allocated[index] += 1
    return dict(zip(source_ids, allocated))


def required_source_schema(source_ids: list[str], line_schema: dict[str, Any]) -> dict[str, Any]:
    source_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"lines": {"type": "array", "items": line_schema}, "complete": {"type": "boolean"}},
        "required": ["lines", "complete"],
    }
    return {
        "type": "object", "additionalProperties": False,
        "properties": {source: source_schema for source in source_ids},
        "required": list(source_ids),
    }


def extract_required_sources(content: str, source_ids: list[str]) -> tuple[list[dict[str, Any]], bool]:
    return extract_source_lines(content, source_ids)


deps.register(__name__, ["DraftBeat", "allocate_source_targets", "build_draft_packets",
                         "extract_required_sources", "packet_chapters", "planned_draft_beats",
                         "required_source_schema"])

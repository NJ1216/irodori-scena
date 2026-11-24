from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from server.registry import deps

SUMMARY_BLOCK_LINES = 50


def _content_hash(rows: list[dict[str, Any]]) -> str:
    import hashlib
    import json

    projection = [
        {"speaker": row.get("speaker", ""), "text": row.get("line", row).get("text", "")}
        for row in rows
    ]
    encoded = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def clear_script_assistant_summary_cache(project_id: str | None = None) -> None:
    with deps.SCRIPT_ASSISTANT_SUMMARY_CACHE_LOCK:
        if project_id is None:
            deps.SCRIPT_ASSISTANT_SUMMARY_CACHE.clear()
            return
        for key in list(deps.SCRIPT_ASSISTANT_SUMMARY_CACHE):
            if key[0] == project_id:
                deps.SCRIPT_ASSISTANT_SUMMARY_CACHE.pop(key, None)


def summarize_unit(
    request: Any, job_id: str, project_id: str, unit_id: str, rows: list[dict[str, Any]],
    prompt_version: str, debug: Path, *, call: Callable[..., str],
) -> str:
    """Summarize one chapter record, caching only verified non-empty output."""
    model = str(getattr(request, "model", ""))
    if prompt_version.startswith("rewrite-target"):
        system = (
            "あなたは日本語音声台本の書き直し方針要約担当です。完成台詞を書かず、対象で維持する事実、"
            "対象後に必要な到達点、作者要望に沿って変更できる会話経路を簡潔にまとめる。推測、新設定、"
            "台詞の引用・言い換え、Markdown、JSONは禁止。"
        )
    else:
        system = (
            "あなたは日本語音声台本の段階的Context要約担当です。台詞を書き直さず、中心となる出来事、"
            "人物の関係・認識・感情の変化、後続へ影響する約束・秘密・未解決事項、末尾時点の状態だけを"
            "時系列で簡潔にまとめる。推測、新設定、台詞の引用、Markdown、JSONは禁止。"
        )
    summaries: list[str] = []
    for index in range(0, len(rows), SUMMARY_BLOCK_LINES):
        block = rows[index:index + SUMMARY_BLOCK_LINES]
        block_id = f"{unit_id}:block-{index // SUMMARY_BLOCK_LINES}"
        key = (project_id, block_id, _content_hash(block), model, prompt_version)
        with deps.SCRIPT_ASSISTANT_SUMMARY_CACHE_LOCK:
            cached = deps.SCRIPT_ASSISTANT_SUMMARY_CACHE.get(key)
        if cached is not None:
            summaries.append(cached)
            continue
        payload = [{"speaker": row.get("speaker", ""), "text": row.get("line", row).get("text", "")} for row in block]
        value = call(
            request, job_id, system=system, user={"dialogue": payload}, max_tokens=700, temperature=0.2,
            path=debug / f"summary-{unit_id.replace(':', '-')}-{index // SUMMARY_BLOCK_LINES + 1}.txt",
            feature="script-assistant-summary",
        ).strip()
        if value:
            summaries.append(value)
            with deps.SCRIPT_ASSISTANT_SUMMARY_CACHE_LOCK:
                for stale in list(deps.SCRIPT_ASSISTANT_SUMMARY_CACHE):
                    if (stale[0], stale[1], stale[3], stale[4]) == (project_id, block_id, model, prompt_version):
                        deps.SCRIPT_ASSISTANT_SUMMARY_CACHE.pop(stale, None)
                deps.SCRIPT_ASSISTANT_SUMMARY_CACHE[key] = value
    if not summaries:
        raise RuntimeError(f"Context層「{prompt_version}」の要約を作成できませんでした。")
    return " → ".join(summaries)


def summarize_rewrite_target(
    request: Any, job_id: str, project_id: str, group_id: str,
    rows: list[dict[str, Any]], debug: Path, *, call: Callable[..., str],
) -> str:
    if len(rows) <= SUMMARY_BLOCK_LINES:
        return ""
    compact = [{"speaker": row["speaker"], "text": row["text"]} for row in rows]
    return summarize_unit(
        request, job_id, project_id, f"{group_id}:rewrite-target", compact,
        "rewrite-target-v1", debug, call=call,
    )


deps.register(__name__, ["clear_script_assistant_summary_cache", "summarize_rewrite_target", "summarize_unit"])

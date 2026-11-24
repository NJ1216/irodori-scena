from __future__ import annotations

from typing import Any

from server.registry import deps


def _row(prefix: str, item: dict[str, Any]) -> str:
    fields = [prefix, item["alias"], item["name"], item["text"]]
    if "emoji_allowed" in item:
        fields.append(f"表情EMOJI={'許可' if item['emoji_allowed'] else '禁止'}")
    for label, key in (("既存話速", "rate"), ("既存間隔", "gap"), ("既存ト書き", "stage")):
        if item[key] not in (None, "", "未設定"):
            fields.append(f"{label}={item[key]}")
    return "|".join(str(value) for value in fields)


def build_direction_prompt(
    request: Any,
    rows: list[dict[str, Any]],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    cast_context: list[dict[str, Any]] | None = None,
    *,
    benchmark_prompt_order: str = "cache-first",
) -> tuple[str, dict[str, Any]]:
    enabled = [
        label
        for flag, label in (
            (request.emoji_expressions, "表情EMOJIの挿入"),
            (request.speech_rate, "話速"),
            (request.gap_seconds, "発話後の間"),
            (request.stage_direction, "ト書き"),
        )
        if flag
    ]
    emoji = "、".join(sorted(deps.ai_allowed_emojis(request, request.allowed_emojis))) or "なし"
    overwrite_rule = (
        "既存の話速・発話間隔・ト書き・表情EMOJIは今回の演出で置き換えてよい。"
        if request.overwrite_existing
        else "既存の話速・発話間隔・ト書きは変更せず、未設定の項目だけを提案する。既存の表情EMOJIがある行には表情EMOJIを提案しない。"
    )
    emoji_rules = deps.EMOJI_PERFORMANCE_RULEBOOK if request.emoji_expressions and emoji != "なし" else ""
    fixed_system = (
        "You are the performance director for a Japanese voice drama. Direct only the requested lines. "
        "Never rewrite, translate, quote, or continue spoken text. Respect each cast profile, first/second-person "
        "forms, forms of address, relationships, and established speaking style. Return no explanation or Markdown.\n"
        + emoji_rules
        + "\n【Output protocol / 出力形式】\n"
        "Return exactly one `L番号|項目名=値|...` record per requested line, in input order. "
        "Use only emoji, rate, gap, direction fields; never emit the spoken text as a field. "
        "direction must be concise natural Japanese without EMOJI, dialogue, parentheses, or metadata. "
        "emoji uses `絵文字列@元本文に完全一致する連続語句`, with proposals separated by `;`. "
        "The anchor must be the shortest unambiguous phrase and must not include an existing EMOJI. "
        "Choose a natural phrase boundary and never split a word: use `😊@おはよう` for `おはようございます`, "
        "not `😊@おは`. "
        "Use one EMOJI normally, two only for clear emphasis, and three only for exceptional emphasis. "
        "Do not copy an existing EMOJI mechanically, repeat the same anchor, decorate every line, or use 📢 for volume. "
        "Omit emoji when no precise audible effect is justified. A row marked 表情EMOJI=禁止 must omit the emoji field.\n"
    )
    request_settings = (
        (
            "既存のIrodori-TTS表情EMOJIを置き換え、許可済み表情EMOJIだけを設定する。"
            if request.overwrite_existing
            else "既存のIrodori-TTS表情EMOJIを消さず、許可済み表情EMOJIだけを追加する。"
        )
        + f"今回返す項目は{'・'.join(enabled)}だけ。許可EMOJI: {emoji}。"
        + overwrite_rule
        + f"rateは{request.speech_rate_min:.2f}〜{request.speech_rate_max:.2f}、"
        f"gapは{request.gap_min:.2f}〜{request.gap_max:.2f}。rateとgapは省略可、directionは非空でEMOJIなし。"
    )
    if getattr(request, "allow_negative_gap", False):
        request_settings += (
            " gapは現在行の発話終了から次の発話単位の開始までの符号付き秒数である。"
            "負値は、次の台詞を現在行が終わる前に明示的に開始させる被せ・割り込みが演出上必要な場合だけ使う。"
            "単なる素早い応答、自然な会話継続、間を詰めるだけの場面には負値を使わず0以上にする。"
            "割り込む後発行自身ではなく、その直前の先行行のgapへ負値を設定する。"
            "cueは複数行の全文を同時開始する指定であり、被せ・割り込みの代用にしない。"
            "cue候補内では最後のメンバーのgapだけを同時発話群の後の間として判断し、それ以外のメンバーへ負値を付けない。"
        )
    if benchmark_prompt_order not in {"production", "cache-first"}:
        raise ValueError(f"unknown benchmark prompt order: {benchmark_prompt_order}")
    system = fixed_system + (
        "【Request settings / 今回の設定】\n" + request_settings if benchmark_prompt_order == "production" else ""
    )
    context = [
        *(_row("変更不可の直前文脈", item) for item in before),
        *(_row("変更対象", item) for item in rows),
        *(_row("変更不可の直後文脈", item) for item in after),
    ]
    if benchmark_prompt_order == "cache-first":
        user = {"sections": [
            {"request_settings": request_settings}, {"participating_casts": cast_context or []},
            {"lines": "\n".join(context)},
        ]}
    else:
        user = {"participating_casts": cast_context or [], "lines": "\n".join(context)}
    return system, user


deps.register(__name__, ["build_direction_prompt"])

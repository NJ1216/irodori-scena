from __future__ import annotations

from typing import Any

from server.registry import deps


def _system_prompt(request: Any, group: dict[str, Any], simultaneous_requirement: str = "") -> str:
    if request.operation == "cast-compose":
        return (
            "あなたは日本語音声台本のキャスト整合編集者です。各対象行を、指定キャストのプロフィール、"
            "台本内設定、前後の会話と照合する。プロフィールから逸脱する語彙、口調、価値判断、反応だけを"
            "自然に整え、逸脱していない本文は変えない。事実、意図、話者、行数、順番、ト書き、演出値は変えない。"
            "original_target_rows の rewrite_id と emoji placeholder を各行で正確に維持する。"
            "preceding_processed_rows は直前までに確定した処理結果なので、会話の連続性を保つ。"
            "出力は一発話一行の `R1|A|本文` 形式とし、対象行を省略しない。JSON、Markdown、説明は禁止。"
        )
    policy = deps.performance_direction_policy(request)
    if request.operation == "paraphrase":
        mode = (
            "元行と同じ順番・話者・事実・意図を保ち、各行を別の自然な表現へ言い換える。"
            "各行は元行と同程度の長さを目安にするが、文字数の完全一致は要求しない。行の追加・削除は禁止。"
            "original_target_rows の rewrite_id を各出力行の先頭へ正確に維持する。"
            "各行で語彙、構文、情報の焦点、台詞のリズムのうち複数を変える。固有名詞や必須用語を除き、"
            "特徴的な言い回しをそのまま再利用せず、語尾だけを変えた提案は禁止する。"
        )
    elif group["fixed"]:
        mode = (
            "書き直し方針に示された置換位置の役割どおり、指定された飛び飛びの行だけを順番どおり"
            "一行ずつ完全に書き直す。行の追加・削除と未選択行の変更は禁止。"
        )
    elif request.operation == "rewrite":
        mode = (
            "書き直し方針に従って対象範囲を新しく執筆する。選択キャスト内で話者・構成・同時発話を"
            "自然に再設計し、入口、ターン配分、感情推移、具体例、文構造のうち複数を元の経路から変える。"
        )
    else:
        mode = "指定位置へ前後につながる新しい発話を挿入する。"
    cue_rule = (
        simultaneous_requirement +
        " 同時発話は `A|本文||emoji=NONE|rate=1.00|gap=0.70|direction=穏やかに|cue=SIM:S1` に続けて、"
        "異なる話者を同じ `cue=SIM:S1` で2〜8行出力する。要件を通常発話だけで済ませてはならない。"
        if simultaneous_requirement else ""
    )
    return (
        "あなたは日本語の音声ドラマ脚本家・演出家です。" + mode +
        "selected_casts の preferences に従う。emoji 禁止の話者はEMOJIなし。fillers 多めの話者は自然なフィラーを増やす。"
        "話者配分を変更できる場合、priority main は多め、supporting は控えめにする。" +
        "変更不可の文脈と後続3行に矛盾させない。出力は一発話一行、通常行は"
        "`A|本文||emoji=NONE|rate=1.00|gap=0.70|direction=穏やかに|cue=NONE` とする。" + cue_rule +
        deps.performance_direction_prompt_rules(policy) + "JSON、Markdown、説明は禁止。"
    )


def _author_instruction(request: Any) -> str:
    if request.instruction.strip():
        return request.instruction
    if request.operation == "paraphrase":
        return "意味を保ちながら語彙・文構造・台詞のリズムを変え、語尾だけの変更ではない自然な別表現にする"
    if request.operation == "cast-compose":
        return "キャスト設定から逸脱している箇所だけを整え、適合している台詞は維持する"
    return "前後の文脈に自然につながるようにする"

from __future__ import annotations

import re
from typing import Any

SIMULTANEOUS_REQUEST = re.compile(r"(?:同時|動時)\s*発話|同時に|一斉に|声(?:を|が)?\s*(?:重ね|重な)")
SIMULTANEOUS_NEGATION = re.compile(r"(?:同時|動時)\s*発話.{0,8}(?:なし|不要|禁止|しない|避け)")
SIMULTANEOUS_LEAD_IN = re.compile(r"掛け声|合図|きっかけ")


def _explicitly_requests_simultaneous(request: Any) -> bool:
    instruction = request.instruction.strip()
    return bool(SIMULTANEOUS_REQUEST.search(instruction) and not SIMULTANEOUS_NEGATION.search(instruction))


def _simultaneous_requirement(request: Any) -> str:
    if request.operation not in {"insert", "rewrite"} or not _explicitly_requests_simultaneous(request):
        return ""
    return (
        "作者が同時発話を明示している。作者が指定した入口と順序に従い、異なる2名以上の連続する発話へ"
        "同じ `cue=SIM:S1` を必ず設定する。片方の掛け声の後に同時の挨拶を求める場合は、"
        "掛け声を `cue=NONE` にし、続く挨拶行を同じcueにする。"
    )


def _minimum_simultaneous_lines(request: Any) -> int:
    return 3 if SIMULTANEOUS_LEAD_IN.search(request.instruction) else 2

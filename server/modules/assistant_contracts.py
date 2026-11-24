from __future__ import annotations

from server.registry import deps


def instruction_contract():
    schema = {"type": "object", "additionalProperties": False, "properties": {
        "field": {"type": "string", "enum": ["instruction"]}, "value": {"type": "string"},
    }, "required": ["field", "value"]}
    def legacy(content: str):
        value = deps.parse_instruction(content)
        return [{"field": "instruction", "value": value}] if value else []
    return deps.LlmRecordContract(
        "instruction", 2, schema, "field", frozenset({"instruction"}),
        legacy_suffix="INSTRUCTION|内容の一行だけを返す。", legacy_parser=legacy,
    )


def assistant_line_contract():
    nullable = {"type": ["string", "null"]}
    properties = {
        "line": {"type": "string"}, "text": {"type": "string"},
        "emoji": nullable, "rate": nullable, "gap": nullable, "direction": nullable, "cue": nullable,
    }
    schema = {"type": "object", "additionalProperties": False,
              "properties": properties, "required": list(properties)}
    def legacy(content: str):
        parsed = deps.parse_generated_lines(content) or []
        return [{"line": f"L{index}", "text": row.get("text", ""), "emoji": None,
                 "rate": str(row.get("speech_rate", "")) or None,
                 "gap": str(row.get("gap_seconds", "")) or None,
                 "direction": row.get("stage_direction") or None, "cue": None}
                for index, row in enumerate(parsed, 1)]
    return deps.LlmRecordContract(
        "line-assistant", 1, schema, "line", legacy_suffix=(
            "LINE|本文||emoji=NONE|rate=1.00|gap=0.70|direction=穏やかに|cue=NONE形式だけを返す。"
            "旧 `LINE|本文|ト書き|話速|間|表情注釈` も受理するが出力には使わない。"
        ), legacy_parser=legacy, merge_by_owner=False,
    )


def project_assistant_lines(records) -> str:
    return "\n".join(
        "LINE|{text}||emoji={emoji}|rate={rate}|gap={gap}|direction={direction}|cue={cue}".format(
            text=row.get("text", ""), emoji=row.get("emoji") or "NONE", rate=row.get("rate") or "1.00",
            gap=row.get("gap") or "0.70", direction=row.get("direction") or "NONE", cue=row.get("cue") or "NONE",
        ) for row in records
    )


deps.register(__name__, ["assistant_line_contract", "instruction_contract", "project_assistant_lines"])

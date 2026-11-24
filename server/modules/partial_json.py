"""Bounded JSON scanner retaining closed fields in unfinished containers.

Only structural children are exposed. Braces inside strings never create records.
Malformed scalar siblings are skipped at their own delimiter; unfinished strings
are never guessed. First declarations win, including duplicate ownership keys.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class JsonNode:
    kind: str
    value: Any = None
    closed: bool = False
    members: list[tuple[str, JsonNode]] = field(default_factory=list)
    items: list[JsonNode] = field(default_factory=list)

    def fields(self) -> dict[str, JsonNode]:
        result: dict[str, JsonNode] = {}
        for key, child in self.members:
            result.setdefault(key, child)
        return result

    def materialize(self) -> Any:
        if self.kind == "object":
            return {key: child.materialize() for key, child in self.fields().items()
                    if child.closed or child.kind in {"object", "array"}}
        if self.kind == "array":
            return [child.materialize() for child in self.items
                    if child.closed or child.kind in {"object", "array"}]
        return self.value


class JsonScanner:
    def __init__(self, content: str):
        self.content = content
        self.index = 0
        self.nodes = 0
        self.decoder = json.JSONDecoder()

    def whitespace(self) -> None:
        while self.index < len(self.content) and self.content[self.index].isspace():
            self.index += 1

    def string(self) -> JsonNode:
        start = self.index
        self.index += 1
        escaped = False
        while self.index < len(self.content):
            if self.index - start > 1_048_576:
                raise ValueError("LLM JSON field size limit exceeded")
            char = self.content[self.index]
            self.index += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                try:
                    return JsonNode("scalar", self.decoder.raw_decode(self.content, start)[0], True)
                except ValueError:
                    return JsonNode("invalid")
        return JsonNode("invalid")

    def value(self, depth: int = 0) -> JsonNode:
        self.whitespace()
        self.nodes += 1
        if depth > 32 or self.nodes > 32768:
            raise ValueError("LLM JSON nesting or record count limit exceeded")
        if self.index >= len(self.content):
            return JsonNode("invalid")
        char = self.content[self.index]
        if char == '"':
            return self.string()
        if char in "{[":
            return self.container(char, depth)
        start = self.index
        while self.index < len(self.content) and self.content[self.index] not in ',]}':
            # A malformed sibling can contain quoted delimiters or containers.
            if self.content[self.index] in '{["':
                self.value(depth + 1)
            else:
                self.index += 1
        try:
            value, end = self.decoder.raw_decode(self.content, start)
            if self.content[end:self.index].strip():
                return JsonNode("invalid")
            return JsonNode("scalar", value, True)
        except ValueError:
            return JsonNode("invalid")

    def container(self, opening: str, depth: int) -> JsonNode:
        node = JsonNode("object" if opening == "{" else "array")
        closing = "}" if opening == "{" else "]"
        self.index += 1
        while self.index < len(self.content):
            self.whitespace()
            if self.index >= len(self.content):
                break
            char = self.content[self.index]
            if char == closing:
                self.index += 1
                node.closed = True
                break
            if char in "}]":
                break  # Mismatched hierarchy cannot be repaired unambiguously.
            if char == ",":
                self.index += 1
                continue
            start = self.index
            if node.kind == "array":
                node.items.append(self.value(depth + 1))
            else:
                self.member(node, depth)
            if self.index == start:
                break
        return node

    def member(self, node: JsonNode, depth: int) -> None:
        if self.content[self.index] != '"':
            self.value(depth + 1)
            return
        key = self.string()
        self.whitespace()
        if self.index >= len(self.content) or self.content[self.index] != ":":
            return
        self.index += 1
        child = self.value(depth + 1)
        if key.closed and isinstance(key.value, str):
            node.members.append((key.value, child))


def scan_json_object(content: str) -> JsonNode:
    scanner = JsonScanner(content)
    # Permit prose/fences surrounding a root object, but never a quoted lookalike.
    while scanner.index < len(content):
        if content[scanner.index] == '"':
            scanner.string()
        elif content[scanner.index] == "{":
            return scanner.value()
        else:
            scanner.index += 1
    return JsonNode("invalid")


def extract_partial_records(content: str) -> tuple[list[dict[str, Any]], bool]:
    root = scan_json_object(content)
    records = root.fields().get("records", JsonNode("invalid"))
    rows = [item.materialize() for item in records.items if item.kind == "object"]
    return rows, not root.closed or not records.closed


def extract_source_lines(content: str, source_ids: list[str]) -> tuple[list[dict[str, Any]], bool]:
    if not content.strip():
        return [], False
    root = scan_json_object(content)
    records, completed, seen_sources = [], set(), set()
    for source, value in root.members:
        if source not in source_ids or value.kind != "object" or source in seen_sources:
            continue
        lines = value.fields().get("lines", JsonNode("invalid"))
        accepted = []
        seen = set()
        for line in lines.items:
            row = line.materialize() if line.kind == "object" else {}
            if not isinstance(row.get("text"), str):
                continue
            identity = (str(row.get("speaker", "")), row["text"])
            if identity in seen:
                continue
            seen.add(identity)
            accepted.append({**row, "source": source})
        if accepted:
            seen_sources.add(source)
        state = value.fields().get("complete")
        # Older saved responses have no explicit semantic completion field.
        finished = state is None or (state.closed and state.value is True)
        if value.closed and (lines.closed or lines.kind == "scalar") and finished:
            completed.add(source)
            for row in accepted:
                row["source_complete"] = True
        records.extend(accepted)
    return records, not root.closed or set(source_ids) != completed

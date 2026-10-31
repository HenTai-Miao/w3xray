"""Flat JSON evidence with duplicate members and exact source token spans.

The parser consumes decoded text. Callers retain the original bytes and encoding
when byte offsets are required; node offsets refer to the supplied characters.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re


@dataclass(frozen=True, slots=True)
class JsonMember:
    """One object member, including every occurrence of a repeated key."""

    key: str
    node: int


@dataclass(frozen=True, slots=True)
class JsonNode:
    """Flat JSON syntax tree; numbers retain their original token spelling."""

    kind: str
    start: int
    end: int
    value: str | bool | None = None
    members: tuple[JsonMember, ...] = ()
    elements: tuple[int, ...] = ()


_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_STRING_DECODER = json.JSONDecoder()


@dataclass(slots=True)
class _Frame:
    kind: str
    start: int
    members: list[JsonMember]
    elements: list[int]
    state: str
    key: str = ""


def parse_json_evidence(text: str) -> tuple[tuple[JsonNode, ...], int]:
    """Parse strict JSON with an explicit stack and exact numeric tokens."""
    nodes: list[JsonNode] = []
    stack: list[_Frame] = []
    root: int | None = None
    pos = 0

    def error(message: str) -> ValueError:
        return ValueError(f"JSON 字符偏移 {pos}: {message}")

    def attach(node: JsonNode) -> None:
        nonlocal root
        index = len(nodes)
        nodes.append(node)
        if not stack:
            root = index
        elif stack[-1].kind == "object":
            stack[-1].members.append(JsonMember(stack[-1].key, index))
            stack[-1].state = "comma"
        else:
            stack[-1].elements.append(index)
            stack[-1].state = "comma"

    while True:
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1
        if not stack and root is not None:
            if pos != len(text):
                raise error("根值后还有内容")
            return tuple(nodes), root
        if pos >= len(text):
            raise error("文件结束前 JSON 值未完成")
        frame = stack[-1] if stack else None
        token = text[pos]
        if frame is not None:
            closing = "}" if frame.kind == "object" else "]"
            if frame.state in {"first", "comma"} and token == closing:
                stack.pop()
                pos += 1
                attach(
                    JsonNode(
                        frame.kind,
                        frame.start,
                        pos,
                        members=tuple(frame.members),
                        elements=tuple(frame.elements),
                    )
                )
                continue
            if frame.state == "comma":
                if token != ",":
                    raise error("需要逗号或容器结束符")
                frame.state = "key" if frame.kind == "object" else "value"
                pos += 1
                continue
            if frame.kind == "object" and frame.state in {"first", "key"}:
                if token != '"':
                    raise error("对象键必须为字符串")
                try:
                    decoded_key, pos = _STRING_DECODER.raw_decode(text, pos)
                    if not isinstance(decoded_key, str):
                        raise error("对象键必须为字符串")
                    frame.key = decoded_key
                except ValueError as exc:
                    raise error(str(exc)) from exc
                frame.state = "colon"
                continue
            if frame.state == "colon":
                if token != ":":
                    raise error("对象键后需要冒号")
                frame.state = "value"
                pos += 1
                continue
        start = pos
        if token in "{[":
            stack.append(
                _Frame("object" if token == "{" else "array", pos, [], [], "first")
            )
            pos += 1
        elif token == '"':
            try:
                value, pos = _STRING_DECODER.raw_decode(text, pos)
                if not isinstance(value, str):
                    raise error("字符串未完成")
            except ValueError as exc:
                raise error(str(exc)) from exc
            attach(JsonNode("string", start, pos, value))
        elif token in "-0123456789":
            matched = _NUMBER.match(text, pos)
            if matched is None:
                raise error("无效数字")
            pos = matched.end()
            attach(JsonNode("number", start, pos, matched.group()))
        else:
            literal = next(
                (s for s in ("true", "false", "null") if text.startswith(s, pos)), None
            )
            if literal is None:
                raise error("无效 JSON 值；NaN/Infinity 不属于 JSON")
            pos += len(literal)
            attach(
                JsonNode(
                    "null" if literal == "null" else "boolean",
                    start,
                    pos,
                    {"true": True, "false": False, "null": None}[literal],
                )
            )


__all__ = ("JsonMember", "JsonNode", "parse_json_evidence")

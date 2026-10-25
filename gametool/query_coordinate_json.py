"""Iterative JSON evidence for coordinate handoffs, without materializing inventories."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from json import JSONDecoder
import re

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_KEYS = frozenset({"x", "y", "radius", "selected", "selected_unit"})
_SELECTED = frozenset({"selected", "selected_unit"})
_WHITESPACE = " \t\r\n"
_LABEL = re.compile(r'\[[^\[\]{}"\r\n]*\]|\{[^{}\[\]"\r\n]*\}')
_DECODER = JSONDecoder()

type JsonValue = str | JsonObject | None


@dataclass(slots=True)
class JsonObject:
    fields: dict[str, list[JsonValue]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JsonEvidence:
    objects: tuple[JsonObject, ...]
    outside: str
    present: bool = False
    invalid: bool = False


@dataclass(slots=True)
class _Frame:
    kind: str
    state: str
    root: bool = False
    result: JsonObject | None = None
    key: str = ""


def _space(text: str, position: int) -> int:
    while position < len(text) and text[position] in _WHITESPACE:
        position += 1
    return position


def _string(text: str, position: int) -> tuple[str, int]:
    # Only scalar strings use the standard decoder; containers use our stack.
    value, end = _DECODER.raw_decode(text, position)
    if not isinstance(value, str):
        raise ValueError("Expected JSON string")
    return value, end


def _document(text: str, start: int) -> tuple[JsonObject | None, int]:
    """Validate every token using a stack; retain only root and selected fields."""
    stack: list[_Frame] = []
    position = start
    root: JsonObject | None = None

    def deliver(value: JsonValue) -> None:
        nonlocal root
        if not stack:
            root = value if isinstance(value, JsonObject) else None
            return
        parent = stack[-1]
        if parent.result is not None and parent.key in _KEYS:
            parent.result.fields.setdefault(parent.key, []).append(value)
        parent.key = ""

    while True:
        position = _space(text, position)
        if position >= len(text):
            raise ValueError("Unclosed JSON value")
        char = text[position]
        if stack:
            frame = stack[-1]
            if frame.state in {"key", "key-or-end"}:
                if char == "}" and frame.state == "key-or-end":
                    stack.pop()
                    deliver(frame.result)
                    position += 1
                    if not stack:
                        return root, position
                    continue
                if char != '"':
                    raise ValueError("Expected JSON object key")
                frame.key, position = _string(text, position)
                position = _space(text, position)
                if position >= len(text) or text[position] != ":":
                    raise ValueError("Expected JSON colon")
                frame.state = "value"
                position += 1
                continue
            if frame.state == "after":
                closing = "}" if frame.kind == "object" else "]"
                if char == closing:
                    stack.pop()
                    deliver(frame.result)
                    position += 1
                    if not stack:
                        return root, position
                    continue
                if char != ",":
                    raise ValueError("Expected JSON separator")
                frame.state = "key" if frame.kind == "object" else "value"
                position += 1
                continue
            if char == "]" and frame.state == "value-or-end":
                stack.pop()
                deliver(None)
                position += 1
                if not stack:
                    return root, position
                continue
        capture = not stack or stack[-1].root and stack[-1].key in _SELECTED
        is_root = not stack
        if stack:
            stack[-1].state = "after"
        if char in "{[":
            stack.append(
                _Frame(
                    "object" if char == "{" else "array",
                    "key-or-end" if char == "{" else "value-or-end",
                    is_root,
                    JsonObject() if capture and char == "{" else None,
                )
            )
            position += 1
            continue
        value: JsonValue = None
        if char == '"':
            _value, position = _string(text, position)
        elif number := _NUMBER.match(text, position):
            value, position = number.group(), number.end()
        else:
            literal = next(
                (
                    word
                    for word in ("true", "false", "null")
                    if text.startswith(word, position)
                ),
                None,
            )
            if literal is None:
                raise ValueError("Invalid JSON value")
            position += len(literal)
        deliver(value)
        if not stack:
            return root, position


def _json_container(text: str, position: int) -> bool:
    char = text[position]
    following = _space(text, position + 1)
    if following >= len(text):
        return True
    if char == "{":
        return text[following] in '"}' or _LABEL.match(text, position) is None
    return (
        text[following] in '"{[]-0123456789'
        or any(text.startswith(word, following) for word in ("true", "false", "null"))
        or _LABEL.match(text, position) is None
    )


@lru_cache(maxsize=8)
def coordinate_json(text: str) -> JsonEvidence:
    """Visit complete documents and fragments; quoted text is never coordinate syntax."""
    first = _space(text, 0)
    if first < len(text) and text[first] == '"':
        try:
            key, end = _string(text, first)
            end = _space(text, end)
            if key in _KEYS and end < len(text) and text[end] == ":":
                wrapped = "{" + text + "}"
                root, end = _document(wrapped, 0)
                if _space(wrapped, end) != len(wrapped):
                    raise ValueError("Extra JSON fragment text")
                return JsonEvidence((root,) if root is not None else (), "", True)
        except ValueError:
            return JsonEvidence((), "", True, True)
    objects: list[JsonObject] = []
    outside: list[str] = []
    cursor = position = 0
    present = False
    while position < len(text):
        if text[position] in "{[" and _json_container(text, position):
            try:
                root, end = _document(text, position)
            except ValueError:
                return JsonEvidence((), "", True, True)
            present = True
            if root is not None:
                objects.append(root)
        elif text[position] == '"':
            try:
                _value, end = _string(text, position)
            except ValueError:
                end = len(text)
        else:
            position += 1
            continue
        outside.extend((text[cursor:position], "\0"))
        cursor = position = end
    outside.append(text[cursor:])
    return JsonEvidence(tuple(objects), "".join(outside), present)

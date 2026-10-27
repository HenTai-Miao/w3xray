"""Complete iterative JSON codec for offline live evidence.

Fractional JSON numbers retain their original token.  Neither the interpreter's
integer-string quota nor its recursion limit determines report coverage.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from json import JSONDecoder, dumps
import math
import re
from typing import Any

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_SPACE = " \t\r\n"
_STRINGS = JSONDecoder()


class LiveReportError(ValueError):
    """Invalid, unstable, or unsafe report evidence."""


def integer_from_text(text: str) -> int:
    """Convert a validated integer token without a decimal digit quota."""
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    result = 0
    for start in range(0, len(digits), 9):
        block = digits[start : start + 9]
        result = result * (10 ** len(block)) + int(block)
    return -result if negative else result


def integer_to_text(value: int) -> str:
    """Format every encoded integer without changing global interpreter state."""
    if value == 0:
        return "0"
    negative = value < 0
    remaining = -value if negative else value
    blocks: list[int] = []
    while remaining:
        remaining, block = divmod(remaining, 1_000_000_000)
        blocks.append(block)
    result = str(blocks.pop()) + "".join(f"{block:09d}" for block in reversed(blocks))
    return "-" + result if negative else result


@dataclass(frozen=True, slots=True)
class ExactJsonNumber:
    """A finite JSON number, including values outside binary-float precision."""

    text: str

    def __post_init__(self) -> None:
        if _NUMBER.fullmatch(self.text) is None:
            raise LiveReportError(f"Invalid finite JSON number: {self.text!r}")

    def __str__(self) -> str:
        return self.text

    def identity(self) -> tuple[bool, str, int]:
        token = self.text
        negative = token.startswith("-")
        token = token.lstrip("-")
        coefficient, marker, exponent_text = token.lower().partition("e")
        exponent = 0
        if marker:
            exponent = integer_from_text(exponent_text.lstrip("+"))
        whole, dot, fraction = coefficient.partition(".")
        digits = (whole + fraction).lstrip("0")
        if not digits:
            return False, "0", 0
        exponent -= len(fraction) if dot else 0
        significant = digits.rstrip("0")
        exponent += len(digits) - len(significant)
        return negative, significant, exponent

    def to_dict(self) -> dict[str, str]:
        # JSON-compatible transport for consumers using the standard encoder.
        # The exact codec emits this value as a JSON number, never as this tag.
        return {"value_type": "exact-json-number", "value": self.text}


@dataclass(slots=True)
class _Frame:
    container: dict[str, Any] | list[Any]
    state: str
    key: str = ""
    keys: set[str] = field(default_factory=set)


def _space(text: str, position: int) -> int:
    while position < len(text) and text[position] in _SPACE:
        position += 1
    return position


def _string(text: str, position: int) -> tuple[str, int]:
    try:
        value, end = _STRINGS.raw_decode(text, position)
    except ValueError as exc:
        raise LiveReportError(
            f"Invalid JSON string at character {position}: {exc}"
        ) from exc
    if not isinstance(value, str):
        raise LiveReportError(f"Expected JSON string at character {position}")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise LiveReportError("Report strings must be strict UTF-8") from exc
    return value, end


def parse_report_json(text: str) -> Any:
    """Validate and retain the whole document, rejecting duplicate object keys."""
    stack: list[_Frame] = []
    root: Any = None
    delivered = False
    position = 0

    def deliver(value: Any) -> None:
        nonlocal root, delivered
        if not stack:
            if delivered:
                raise LiveReportError("More than one JSON root value")
            root, delivered = value, True
            return
        frame = stack[-1]
        if isinstance(frame.container, dict):
            frame.container[frame.key] = value
            frame.key = ""
        else:
            frame.container.append(value)
        frame.state = "after"

    while True:
        position = _space(text, position)
        if delivered and not stack:
            if position != len(text):
                raise LiveReportError(f"Trailing JSON data at character {position}")
            return root
        if position == len(text):
            raise LiveReportError("Empty or unfinished JSON document")
        char = text[position]
        if stack:
            frame = stack[-1]
            if frame.state in {"key", "key-or-end"}:
                if char == "}" and frame.state == "key-or-end":
                    stack.pop()
                    deliver(frame.container)
                    position += 1
                    continue
                if char != '"':
                    raise LiveReportError(
                        f"Expected object key at character {position}"
                    )
                key, position = _string(text, position)
                if key in frame.keys:
                    raise LiveReportError(f"Duplicate JSON object key: {key!r}")
                frame.keys.add(key)
                frame.key = key
                position = _space(text, position)
                if position == len(text) or text[position] != ":":
                    raise LiveReportError(f"Expected colon at character {position}")
                frame.state = "value"
                position += 1
                continue
            if frame.state == "after":
                closing = "}" if isinstance(frame.container, dict) else "]"
                if char == closing:
                    stack.pop()
                    deliver(frame.container)
                    position += 1
                    continue
                if char != ",":
                    raise LiveReportError(f"Expected comma at character {position}")
                frame.state = "key" if isinstance(frame.container, dict) else "value"
                position += 1
                continue
            if frame.state == "value-or-end" and char == "]":
                stack.pop()
                deliver(frame.container)
                position += 1
                continue
        if char in "{[":
            stack.append(
                _Frame(
                    {} if char == "{" else [],
                    "key-or-end" if char == "{" else "value-or-end",
                )
            )
            position += 1
            continue
        if char == '"':
            value, position = _string(text, position)
        elif match := _NUMBER.match(text, position):
            token = match.group()
            value = (
                ExactJsonNumber(token)
                if token == "-0" or any(marker in token for marker in ".eE")
                else integer_from_text(token)
            )
            position = match.end()
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
                raise LiveReportError(f"Invalid JSON value at character {position}")
            value = {"true": True, "false": False, "null": None}[literal]
            position += len(literal)
        deliver(value)


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise LiveReportError("Report strings must be strict UTF-8") from exc
        return dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return integer_to_text(value)
    if isinstance(value, ExactJsonNumber):
        return value.text
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LiveReportError(
                "Report numbers must be finite (NaN/Infinity rejected)"
            )
        return repr(value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise LiveReportError(
                "Report numbers must be finite (NaN/Infinity rejected)"
            )
        return ExactJsonNumber(str(value)).text
    raise LiveReportError(f"Unsupported JSON value type: {type(value).__name__}")


def format_report_json(value: Any) -> str:
    """Serialize full evidence iteratively and reject cycles/non-JSON objects."""
    output: list[str] = []
    active: set[int] = set()
    stack: list[tuple[str, Any]] = [("value", value)]
    while stack:
        operation, current = stack.pop()
        if operation == "text":
            output.append(current)
            continue
        if operation == "leave":
            active.remove(current)
            continue
        if isinstance(current, Mapping | list):
            identity = id(current)
            if identity in active:
                raise LiveReportError("Cyclic report containers cannot be serialized")
            active.add(identity)
            stack.append(("leave", identity))
            if isinstance(current, Mapping):
                entries = list(current.items())
                keys: set[str] = set()
                output.append("{")
                stack.append(("text", "}"))
                for index in range(len(entries) - 1, -1, -1):
                    key, child = entries[index]
                    if isinstance(key, int) and not isinstance(key, bool):
                        key = integer_to_text(key)
                    if not isinstance(key, str):
                        raise LiveReportError(
                            "JSON object keys must be strings or integer owner slots"
                        )
                    if key in keys:
                        raise LiveReportError(
                            f"Conflicting serialized JSON object key: {key!r}"
                        )
                    keys.add(key)
                    stack.append(("value", child))
                    stack.append(("text", ":"))
                    stack.append(("text", _scalar(key)))
                    if index:
                        stack.append(("text", ","))
            else:
                output.append("[")
                stack.append(("text", "]"))
                for index in range(len(current) - 1, -1, -1):
                    stack.append(("value", current[index]))
                    if index:
                        stack.append(("text", ","))
        else:
            output.append(_scalar(current))
    return "".join(output)


def json_compatible(value: Any) -> Any:
    """Return ordinary JSON types, representing exact fractions with typed tags."""
    # First validate the full graph, then clone it with an explicit work stack.
    format_report_json(value)
    result: list[Any] = [None]
    stack: list[tuple[Any, Any, Any]] = [(result, 0, value)]
    while stack:
        parent, key, current = stack.pop()
        if isinstance(current, Mapping):
            child: dict[str, Any] = {}
            parent[key] = child
            stack.extend(
                (child, integer_to_text(name) if isinstance(name, int) else name, item)
                for name, item in current.items()
            )
        elif isinstance(current, list):
            items: list[Any] = [None] * len(current)
            parent[key] = items
            stack.extend((items, index, item) for index, item in enumerate(current))
        elif isinstance(current, ExactJsonNumber):
            parent[key] = current.to_dict()
        elif isinstance(current, Decimal):
            parent[key] = ExactJsonNumber(str(current)).to_dict()
        else:
            parent[key] = current
    return result[0]


def scalar_identity(value: Any) -> tuple[Any, ...]:
    """Compare JSON numbers exactly; bool, missing, null and zero stay distinct."""
    if isinstance(value, bool):
        return ("bool", value)
    if isinstance(value, int):
        return ("number", *ExactJsonNumber(integer_to_text(value)).identity())
    if isinstance(value, float | Decimal | ExactJsonNumber):
        return ("number", *ExactJsonNumber(_scalar(value)).identity())
    return (type(value).__name__, value)


def values_equal(old: Any, new: Any) -> bool:
    """Structural equality without recursive Python container comparisons."""
    stack = [(old, new)]
    while stack:
        left, right = stack.pop()
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            if set(left) != set(right):
                return False
            stack.extend((left[key], right[key]) for key in left)
        elif isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                return False
            stack.extend(zip(left, right, strict=True))
        elif isinstance(left, Mapping | list) or isinstance(right, Mapping | list):
            return False
        elif scalar_identity(left) != scalar_identity(right):
            return False
    return True

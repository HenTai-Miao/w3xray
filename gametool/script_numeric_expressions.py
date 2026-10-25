"""Prepared, non-executing arithmetic spans with scalar dependency holes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

from .script_lexing import ScriptViews, script_views
from .script_names import NAME_PATTERN
from .script_scopes import CallSpan, script_structure
from .static_numbers import numeric_literal_end


@dataclass(frozen=True, slots=True)
class NumericOperand:
    start: int
    end: int
    expression: str


@dataclass(frozen=True, slots=True)
class NumericExpression:
    start: int
    end: int
    text: str
    operands: tuple[NumericOperand, ...]

    def render(self, values: Sequence[str]) -> str:
        parts: list[str] = []
        cursor = 0
        for operand, value in zip(self.operands, values, strict=True):
            first, end = operand.start - self.start, operand.end - self.start
            parts.extend((self.text[cursor:first], "(" + value + ")"))
            cursor = end
        parts.append(self.text[cursor:])
        return "".join(parts)


def numeric_prefix(
    views: ScriptViews,
    calls: Mapping[int, CallSpan],
    start: int,
    owner: int | None,
    *,
    lua: bool | None,
) -> NumericExpression | None:
    """Read only this expression, reusing whole-source views and call spans."""
    text = views.arguments
    cursor = start
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    first = cursor
    end = first
    depth = 0
    need_value = True
    operation = False
    operands: list[NumericOperand] = []
    while cursor < len(text):
        char = text[cursor]
        if char.isspace():
            cursor += 1
            continue
        if need_value:
            if char == "(":
                depth += 1
                cursor += 1
                continue
            if char in "+-":
                operation = True
                cursor += 1
                continue
            call = calls.get(cursor)
            if call is not None and call.complete and call.owner == owner:
                stop = call.end
                operands.append(NumericOperand(cursor, stop, text[cursor:stop]))
            elif (stop := numeric_literal_end(text, cursor)) is not None:
                pass
            elif (name := NAME_PATTERN.match(views.syntax, cursor)) is not None:
                stop = name.end()
                operands.append(NumericOperand(cursor, stop, text[cursor:stop]))
            else:
                return None
            cursor, end, need_value = stop, stop, False
            continue
        if char == ")" and depth:
            depth -= 1
            cursor += 1
            end = cursor
            continue
        operator = text[cursor : cursor + 2]
        if operator not in {"**", "//"}:
            operator = char
        if operator not in {"+", "-", "*", "/", "//", "%", "**"} and not (
            operator == "^" and lua is True
        ):
            break
        operation = True
        cursor += len(operator)
        need_value = True
    if need_value or depth or not operation:
        return None
    return NumericExpression(first, end, text[first:end], tuple(operands))


@lru_cache(maxsize=8)
def numeric_expression(text: str, *, lua: bool | None) -> NumericExpression | None:
    views = script_views(text, lua=lua)
    calls = {call.start: call for call in script_structure(text, lua=lua).calls}
    result = numeric_prefix(views, calls, 0, None, lua=lua)
    return (
        result
        if result is not None and not views.arguments[result.end :].strip()
        else None
    )

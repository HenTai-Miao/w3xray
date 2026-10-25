"""Iterative, non-executing numeric expressions and lossless number display."""

from __future__ import annotations

import math
import re


_NUMBER = re.compile(
    r"(?:0[xX][0-9a-fA-F]+|\$[0-9a-fA-F]+|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
)
_PRECEDENCE = {
    "+": 1,
    "-": 1,
    "*": 2,
    "/": 2,
    "//": 2,
    "%": 2,
    "u+": 3,
    "u-": 3,
    "**": 4,
}


def format_number(value: float) -> str:
    """Keep every recoverable float digit, using integers when lossless."""
    text = repr(value)
    if text.endswith(".0") and not (value == 0 and math.copysign(1, value) < 0):
        return text[:-2]
    return text


def static_number(expression: str, *, lua: bool = False) -> float | None:
    """Parse numeric syntax to a finite float without Python AST or recursion.

    Names, calls, attributes and strings are never evaluated. Stack sizes follow
    the supplied expression; nested parentheses and unary chains have no cap.
    """
    try:
        return _parse_number(expression, lua=lua)
    except ValueError, TypeError, ArithmeticError:
        return None


def _parse_number(expression: str, *, lua: bool) -> float:
    values: list[float] = []
    operators: list[str] = []
    need_value = True
    index = 0
    while index < len(expression):
        char = expression[index]
        if char.isspace():
            index += 1
            continue
        if need_value:
            if char == "(":
                operators.append(char)
                index += 1
                continue
            if char in "+-":
                operators.append("u" + char)
                index += 1
                continue
            match = _NUMBER.match(expression, index)
            if match is None:
                raise ValueError("not a static numeric expression")
            raw = match.group()
            value = (
                float(int(raw[1:], 16))
                if raw.startswith("$")
                else float(int(raw, 16))
                if raw.lower().startswith("0x")
                else float(raw)
            )
            if not math.isfinite(value):
                raise ValueError("non-finite literal")
            values.append(value)
            index = match.end()
            need_value = False
            continue
        if char == ")":
            while operators and operators[-1] != "(":
                _apply(values, operators.pop())
            if not operators:
                raise ValueError("unmatched closing parenthesis")
            operators.pop()
            index += 1
            continue
        operator = expression[index : index + 2]
        if operator not in ("**", "//"):
            operator = char
        if operator == "^" and lua:
            operator = "**"
        if operator not in _PRECEDENCE or operator.startswith("u"):
            raise ValueError("unsupported numeric syntax")
        while (
            operators
            and operators[-1] != "("
            and (
                _PRECEDENCE[operators[-1]] > _PRECEDENCE[operator]
                or (
                    _PRECEDENCE[operators[-1]] == _PRECEDENCE[operator]
                    and operator != "**"
                )
            )
        ):
            _apply(values, operators.pop())
        operators.append(operator)
        index += 2 if expression[index : index + 2] in ("**", "//") else 1
        need_value = True
    if need_value:
        raise ValueError("missing numeric operand")
    while operators:
        operator = operators.pop()
        if operator == "(":
            raise ValueError("unmatched opening parenthesis")
        _apply(values, operator)
    if len(values) != 1 or not math.isfinite(values[0]):
        raise ValueError("invalid numeric result")
    return values[0]


def _apply(values: list[float], operator: str) -> None:
    if not values:
        raise ValueError("missing operand")
    right = values.pop()
    if operator in ("u+", "u-"):
        values.append(right if operator == "u+" else -right)
        return
    if not values:
        raise ValueError("missing left operand")
    left = values.pop()
    match operator:
        case "+":
            result = left + right
        case "-":
            result = left - right
        case "*":
            result = left * right
        case "/":
            result = left / right
        case "//":
            result = left // right
        case "%":
            result = left % right
        case "**":
            result = left**right
        case _:
            raise ValueError("unknown numeric operator")
    if not isinstance(result, (float, int)) or not math.isfinite(result):
        raise ValueError("non-finite arithmetic result")
    values.append(result)

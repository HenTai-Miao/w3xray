"""Literal object identifiers shared by static script readers."""

from __future__ import annotations

import re

from .script_lexing import literal_string_value, script_views


def strip_outer_parentheses(value: str) -> str:
    value = value.strip()
    if not value.startswith("("):
        return value
    syntax = script_views(value).syntax
    opened: list[int] = []
    closed: dict[int, int] = {}
    for match in re.finditer(r"[()]", syntax):
        if match.group() == "(":
            opened.append(match.start())
        elif opened:
            closed[opened.pop()] = match.start()
    start, end = 0, len(value)
    while start < end and syntax[start] == "(" and closed.get(start) == end - 1:
        start += 1
        end -= 1
        while start < end and value[start].isspace():
            start += 1
        while end > start and value[end - 1].isspace():
            end -= 1
    return value[start:end]


def literal_object_code(value: str) -> str:
    """Decode one complete four-byte literal, never a dynamic expression."""
    value = strip_outer_parentheses(value)
    wrapped = re.fullmatch(
        r"(?:_G\s*\.\s*)?FourCC\s*\((.*)\)",
        script_views(value).arguments,
        re.DOTALL,
    )
    if wrapped:
        literal = literal_string_value(strip_outer_parentheses(wrapped.group(1)))
    elif value.startswith("'"):
        literal = literal_string_value(value)
    else:
        literal = None
    if literal is not None:
        return (
            literal
            if len(literal) == 4 and all(ord(char) <= 255 for char in literal)
            else ""
        )
    try:
        if re.fullmatch(r"\$[0-9a-fA-F]+", value):
            digits = value[1:].lstrip("0") or "0"
            if len(digits) > 8:
                return ""  # A Warcraft object ID is exactly four bytes.
            number = int(digits, 16)
        elif re.fullmatch(r"0[xX][0-9a-fA-F]+", value):
            digits = value[2:].lstrip("0") or "0"
            if len(digits) > 8:
                return ""
            number = int(digits, 16)
        elif re.fullmatch(r"[0-9]+", value):
            digits = value.lstrip("0") or "0"
            if len(digits) > 10:
                return ""
            number = int(digits)
        else:
            return ""
        return number.to_bytes(4, "big").decode("latin-1")
    except ValueError, OverflowError:
        return ""

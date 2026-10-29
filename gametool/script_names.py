"""Qualified source names with token whitespace and unchanged source offsets."""

from __future__ import annotations

import re

IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
# Boundary-only lexing keeps source Unicode names intact without expanding the
# qualified-name resolver's supported binding grammar or native identities.
LEXICAL_IDENTIFIER = r"[^\W\d]\w*"
QUALIFIED_NAME = IDENTIFIER + r"(?:\s*[.:]\s*" + IDENTIFIER + r")*"
NAME_PATTERN = re.compile(QUALIFIED_NAME)
_SPACE = re.compile(r"\s+")
_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def qualified_name(syntax: str) -> str | None:
    """Accept a complete prepared syntax fragment, preserving dot/colon semantics."""
    raw = syntax.strip()
    return _SPACE.sub("", raw) if NAME_PATTERN.fullmatch(raw) else None


def rectangle_name(syntax: str) -> str | None:
    """Keep existing Unicode gg_rct_ suffixes as complete variable references."""
    raw = syntax.strip()
    return (
        _SPACE.sub("", raw)
        if re.fullmatch(r"(?:(?:_G|_ENV)\s*\.\s*)?gg_rct_\w+", raw)
        else None
    )


def member_suffix(syntax: str, start: int) -> bool:
    cursor = start - 1
    while cursor >= 0 and syntax[cursor].isspace():
        cursor -= 1
    return cursor >= 0 and syntax[cursor] in ".:"


def name_before(syntax: str, end: int) -> tuple[int, str] | None:
    """Scan one name backwards; work follows the name, never the whole prefix."""
    stop = end
    while stop and syntax[stop - 1].isspace():
        stop -= 1
    cursor = stop
    while cursor:
        token_end = cursor
        while cursor and syntax[cursor - 1] in _CHARS:
            cursor -= 1
        if cursor == token_end:
            return None
        start = cursor
        while cursor and syntax[cursor - 1].isspace():
            cursor -= 1
        if not cursor or syntax[cursor - 1] not in ".:":
            value = qualified_name(syntax[start:stop])
            return (start, value) if value is not None else None
        cursor -= 1
        while cursor and syntax[cursor - 1].isspace():
            cursor -= 1
    return None

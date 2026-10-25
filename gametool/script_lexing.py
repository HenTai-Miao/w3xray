"""Offset-preserving script views shared by static evidence scanners."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
import re

_TOKEN = re.compile(r"//|--|['\"]|\[(=*)\[")
_LONG = re.compile(r"\[(=*)\[")
_LINE_END = re.compile(r"[\r\n]")
_QUOTE_END = {"'": re.compile(r"\\[\s\S]|'"), '"': re.compile(r'\\[\s\S]|"')}
_NON_NEWLINE = re.compile(r"[^\r\n]")


@dataclass(frozen=True, slots=True)
class ScriptViews:
    """All views retain source length, newlines and character offsets."""

    code: str
    arguments: str
    syntax: str
    lua: bool | None


@dataclass(frozen=True, slots=True)
class ScriptLiteral:
    start: int
    end: int
    value: str
    object_code: bool


def _noncode_spans(text: str, lua: bool | None) -> Iterator[tuple[int, int, bool]]:
    cursor = 0
    while (match := _TOKEN.search(text, cursor)) is not None:
        token = match.group()
        if (token == "//" and lua is True) or (token == "--" and lua is False):
            cursor = match.end()
            continue
        long_open = _LONG.match(text, match.end()) if token == "--" else match
        if long_open is not None and long_open.group().startswith("["):
            if lua is False:
                cursor = match.end()
                continue
            close = "]" + long_open.group(1) + "]"
            end = text.find(close, long_open.end())
            end = len(text) if end < 0 else end + len(close)
        elif token in {"//", "--"}:
            line_end = _LINE_END.search(text, match.end())
            end = len(text) if line_end is None else line_end.start()
        else:
            cursor = match.end()
            while (quoted := _QUOTE_END[token].search(text, cursor)) is not None:
                cursor = quoted.end()
                if quoted.group() == token:
                    break
            else:
                cursor = len(text)
            end = cursor
        yield match.start(), end, token not in {"//", "--"}
        cursor = end


def _blank(text: str) -> str:
    return _NON_NEWLINE.sub(" ", text)


def _replace_spans(text: str, spans: list[tuple[int, int]]) -> str:
    parts: list[str] = []
    cursor = 0
    for start, end in spans:
        parts.extend((text[cursor:start], _blank(text[start:end])))
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def _fourcc_argument(text: str, start: int) -> bool:
    """Look back to the actual identifier, without a whitespace-length ceiling."""
    cursor = start - 1
    while cursor >= 0 and text[cursor].isspace():
        cursor -= 1
    if cursor < 0 or text[cursor] != "(":
        return False
    cursor -= 1
    while cursor >= 0 and text[cursor].isspace():
        cursor -= 1
    end = cursor + 1
    while cursor >= 0 and (text[cursor].isalnum() or text[cursor] == "_"):
        cursor -= 1
    return text[cursor + 1 : end].casefold() == "fourcc"


@lru_cache(maxsize=8)
def script_views(text: str, *, lua: bool | None = None) -> ScriptViews:
    """Separate code, comments and literals once for all scanners.

    Pass the known language whenever a source filename is available. None
    retains the legacy mixed-comment convention for source-free callers.
    Cache eviction only causes recomputation; it never excludes input records.
    """
    spans = tuple(_noncode_spans(text, lua))
    comments = [(start, end) for start, end, string in spans if not string]
    arguments = _replace_spans(text, comments)
    strings = [(start, end) for start, end, string in spans if string]
    ordinary = []
    for start, end in strings:
        raw = text[start:end]
        if lua is not True and len(raw) == 6 and raw[0] == raw[-1] == "'":
            continue
        value = literal_string_value(raw)
        if value is not None and len(value) == 4 and _fourcc_argument(arguments, start):
            continue
        ordinary.append((start, end))
    return ScriptViews(
        code=_replace_spans(arguments, ordinary),
        arguments=arguments,
        syntax=_replace_spans(arguments, strings),
        lua=lua,
    )


def literal_string_value(value: str) -> str | None:
    """Read a complete quoted or Lua long-bracket literal, without evaluation."""
    value = value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        cursor = 1
        while (match := _QUOTE_END[value[0]].search(value, cursor)) is not None:
            cursor = match.end()
            if match.group() == value[0]:
                if cursor != len(value):
                    return None
                break
        else:
            return None
        return value[1:-1].replace("\\\\", "\\").replace('\\"', '"').replace("\\'", "'")
    opening = _LONG.match(value)
    if opening is not None:
        close = "]" + opening.group(1) + "]"
        end = value.find(close, opening.end())
        if end >= 0 and end + len(close) == len(value):
            content = value[opening.end() : end]
            if content.startswith("\r\n"):
                content = content[2:]
            elif content.startswith(("\r", "\n")):
                content = content[1:]
            return content
    return None


def script_literals(text: str, *, lua: bool | None = None) -> Iterator[ScriptLiteral]:
    """Retain literal positions and distinguish actual FourCC operands."""
    spans = tuple(_noncode_spans(text, lua))
    arguments = _replace_spans(
        text, [(start, end) for start, end, string in spans if not string]
    )
    for start, end, string in spans:
        if string and (value := literal_string_value(text[start:end])) is not None:
            is_code = (
                len(value) == 4
                and all(ord(char) <= 255 for char in value)
                and (
                    (lua is not True and text[start] == "'")
                    or _fourcc_argument(arguments, start)
                )
            )
            yield ScriptLiteral(start, end, value, is_code)


def script_string_values(
    text: str, *, lua: bool | None = None, include_object_codes: bool = True
) -> Iterator[str]:
    """Yield real literals, excluding comments and unclosed fragments."""
    for literal in script_literals(text, lua=lua):
        if include_object_codes or not literal.object_code:
            yield literal.value

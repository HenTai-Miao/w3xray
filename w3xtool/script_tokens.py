"""Lightweight script token helpers for static JASS/Lua scans."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class NativeCallChunk:
    name: str
    text: str


def script_code_text(script: str) -> str:
    """Blank comments and ordinary string contents while preserving offsets."""
    out: list[str] = []
    index = 0
    size = len(script)
    while index < size:
        char = script[index]
        if char == "/" and index + 1 < size and script[index + 1] == "/":
            end = _line_comment_end(script, index)
            out.append(_blank(script[index:end]))
            index = end
            continue
        if char == "-" and index + 1 < size and script[index + 1] == "-":
            end = _line_comment_end(script, index)
            out.append(_blank(script[index:end]))
            index = end
            continue
        if char == '"':
            end = _quoted_end(script, index)
            segment = script[index:end]
            out.append(segment if _is_fourcc_quote(script, index) else _blank(segment))
            index = end
            continue
        out.append(char)
        index += 1
    return "".join(out)


def iter_native_call_chunks(
    script: str,
    native_re: re.Pattern[str],
) -> Iterator[NativeCallChunk]:
    """Yield balanced native call chunks, including multiline calls."""
    for match in native_re.finditer(script):
        open_index = _call_open(script, match.end())
        if open_index is None:
            continue
        end = _call_end(script, open_index)
        if end is None:
            continue
        yield NativeCallChunk(match.group(1), script[match.start():end])


def _call_open(script: str, start: int) -> int | None:
    index = start
    while index < len(script) and script[index].isspace():
        index += 1
    if index >= len(script) or script[index] != "(":
        return None
    return index


def _call_end(script: str, open_index: int) -> int | None:
    depth = 0
    index = open_index
    while index < len(script):
        char = script[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _line_comment_end(script: str, start: int) -> int:
    end = script.find("\n", start)
    return len(script) if end < 0 else end


def _quoted_end(script: str, start: int) -> int:
    index = start + 1
    while index < len(script):
        char = script[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return index + 1
        index += 1
    return len(script)


def _is_fourcc_quote(script: str, quote_index: int) -> bool:
    prefix = script[max(0, quote_index - 24):quote_index]
    return re.search(r"FourCC\s*\(\s*$", prefix, re.IGNORECASE) is not None


def _blank(segment: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in segment)

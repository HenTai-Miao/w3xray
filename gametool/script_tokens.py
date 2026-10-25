"""Lightweight script token helpers for static JASS/Lua scans."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import re
from typing import Final

from .script_lexing import script_views


@dataclass(frozen=True, slots=True)
class NativeCallChunk:
    name: str
    text: str


# Lua 函数定义前缀的线性判定字符集（等价于原灾难性回溯正则
# r"\bfunction\s+(?:[A-Za-z_][A-Za-z0-9_]*[.:]?)*$"，压缩单行脚本会让其每次
# 匹配回溯数秒）。
_IDENT_START: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_IDENT_CHARS: Final = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_"
)
_NAME_CHAIN_CHARS: Final = _IDENT_CHARS | frozenset(".:")
_CALL_PAREN_RE: Final = re.compile(r"[()]")


def strip_line_comment(line: str, *, lua: bool | None = None) -> str:
    """Remove comments according to the source language, retaining quoted text."""
    return script_views(line, lua=lua).arguments.rstrip()


def is_lua_function_definition(script: str, start: int) -> bool:
    """Return whether ``script[start]`` sits in a Lua function definition name.

    等价于 ``re.search(r"\\bfunction\\s+(?:[A-Za-z_][A-Za-z0-9_]*[.:]?)*$", prefix)``，
    但从行尾反向一次扫描完成，无回溯。
    """
    line_start = script.rfind("\n", 0, start) + 1
    prefix = script[line_start:start]
    index = len(prefix) - 1
    while index >= 0 and prefix[index] in _NAME_CHAIN_CHARS:
        index -= 1
    chain_start = index + 1
    while index >= 0 and prefix[index].isspace():
        index -= 1
    keyword_end = index + 1
    if keyword_end == chain_start:
        return False  # function 与名字链之间缺少空白
    if keyword_end < 8 or prefix[keyword_end - 8 : keyword_end] != "function":
        return False
    before = prefix[keyword_end - 9] if keyword_end > 8 else ""
    if before and before in _IDENT_CHARS:
        return False  # \bfunction 要求词边界
    return _valid_name_chain(prefix[chain_start:])


def _valid_name_chain(segment: str) -> bool:
    index = 0
    size = len(segment)
    while index < size:
        if segment[index] not in _IDENT_START:
            return False
        index += 1
        while index < size and segment[index] in _IDENT_CHARS:
            index += 1
        if index < size and segment[index] in ".:":
            index += 1
    return True


def script_code_text(script: str, *, lua: bool | None = None) -> str:
    """Return offset-preserving code evidence using the known source language."""
    return script_views(script, lua=lua).code


def iter_native_call_chunks(
    script: str,
    native_re: re.Pattern[str],
    *,
    lua: bool | None = None,
) -> Iterator[NativeCallChunk]:
    """Yield balanced native call chunks, including multiline calls."""
    syntax = script_views(script, lua=lua).syntax
    for match in native_re.finditer(syntax):
        open_index = _call_open(syntax, match.end())
        if open_index is None:
            continue
        end = _call_end(syntax, open_index)
        if end is None:
            continue
        yield NativeCallChunk(match.group(1), script[match.start() : end])


def _call_open(script: str, start: int) -> int | None:
    index = start
    while index < len(script) and script[index].isspace():
        index += 1
    if index >= len(script) or script[index] != "(":
        return None
    return index


def _call_end(script: str, open_index: int) -> int | None:
    """数括号找调用体结尾；括号间的字符由正则一次性跳过。"""
    depth = 0
    index = open_index
    search = _CALL_PAREN_RE.search
    while True:
        match = search(script, index)
        if match is None:
            return None
        if match.group(0) == "(":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return match.end()
        index = match.end()

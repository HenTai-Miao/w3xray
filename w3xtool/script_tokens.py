"""Lightweight script token helpers for static JASS/Lua scans."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
import re
from typing import Final


@dataclass(frozen=True, slots=True)
class NativeCallChunk:
    name: str
    text: str


# Lua 函数定义前缀的线性判定字符集（等价于原灾难性回溯正则
# r"\bfunction\s+(?:[A-Za-z_][A-Za-z0-9_]*[.:]?)*$"，压缩单行脚本会让其每次
# 匹配回溯数秒）。
_IDENT_START: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_IDENT_CHARS: Final = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")
_NAME_CHAIN_CHARS: Final = _IDENT_CHARS | frozenset(".:")
_FOURCC_PREFIX_RE: Final = re.compile(r"FourCC\s*\(\s*$", re.IGNORECASE)
_COMMENT_OR_QUOTE_RE: Final = re.compile(r"//|--|['\"]")
_CALL_PAREN_RE: Final = re.compile(r"[()]")


def strip_line_comment(line: str) -> str:
    """Return ``line`` without its trailing ``//`` or ``--`` comment.

    九个脚本索引模块原本各有一份逐字符副本，每个字符做两次 startswith
    注释判断（单图数百万次）；这里用一次正则跳到下一个引号或注释标记，
    引号内的标记按原语义跳过，未闭合引号整行返回。
    """
    index = 0
    while True:
        match = _COMMENT_OR_QUOTE_RE.search(line, index)
        if match is None:
            return line
        if match.group(0) in ("//", "--"):
            return line[: match.start()]
        index = _skip_quoted_span(line, match.start())


def _skip_quoted_span(line: str, start: int) -> int:
    quote = line[start]
    index = start + 1
    size = len(line)
    while index < size:
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return size


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
    if keyword_end < 8 or prefix[keyword_end - 8:keyword_end] != "function":
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


@lru_cache(maxsize=8)
def _script_code_text_cached(script: str) -> str:
    return _script_code_text_impl(script)


def script_code_text(script: str) -> str:
    """Blank comments and ordinary string contents while preserving offsets.

    纯函数；一次地图加载内多个扫描器会对同一脚本重复剥离注释，用小缓存复用。
    """
    return _script_code_text_cached(script)


def _script_code_text_impl(script: str) -> str:
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
    return _FOURCC_PREFIX_RE.search(prefix) is not None


def _blank(segment: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in segment)

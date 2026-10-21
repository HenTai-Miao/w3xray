"""解析 war3map.wts 字符串表，用于还原 TRIGSTR_n 引用。

格式示例：
    STRING 390
    {
    多行文本
    }
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final, Protocol

from .extraction_diagnostics import ComponentParseError
from .war3_encoding import decode_warcraft_string


class _MapWtsSource(Protocol):
    @property
    def ui_strings(self) -> dict[int, str] | None: ...

    @property
    def scripts(self) -> dict[str, str]: ...


_HEADER: Final[re.Pattern[bytes]] = re.compile(rb"STRING\s+(\d+)", re.IGNORECASE)


# 开/闭括号都要求**独占一行**(行首 {/} + 仅尾随空白)：
# - 闭合独占行：避免误伤 GBK 尾字节 0x7D，也避免正文里 "} else {" 这类被当成闭合提前截断。
# - 开括号独占行：避免 STRING 头与正文之间的注释行(如 "// 备注 {x}")里的 { 被当成正文起点。
def _decode_str(b: bytes) -> str:
    """单条字符串解码：UTF-8 后按系统 ACP/GBK 兼容老中文图。"""
    return decode_warcraft_string(b)


def parse_wts(data: bytes) -> dict[int, str]:
    # 在字节层解析，按 STRING 块逐条解码：整文件统一解码会让个别 GBK 片段污染成乱码，
    # 且无法再按条恢复；逐条 UTF-8→GBK 回退可兼容 UTF-8 为主、个别 GBK 的混合编码图。
    if data.startswith(b"\xef\xbb\xbf"):  # 去 UTF-8 BOM
        data = data[3:]
    table: dict[int, str] = {}
    i = 0
    n = len(data)
    while i < n:
        m = _HEADER.search(data, i)
        if not m:
            break
        sid = int(m.group(1))
        opening = _find_structural_line(data, m.end(), b"{")
        if opening is None:  # 兜底：找不到独占行 { 时退回首个 {
            brace = data.find(b"{", m.end())
            if brace < 0:
                break
            body_start = _skip_one_line_ending(data, brace + 1)
        else:
            _opening_start, body_start = opening
        closing = _find_structural_line(data, body_start, b"}")
        if closing is None:
            break
        closing_start, closing_end = closing
        body_end = _remove_one_line_ending(data, body_start, closing_start)
        body = data[body_start:body_end]
        table[sid] = _decode_str(body)
        i = closing_end
    return table


def _find_structural_line(
    data: bytes,
    start: int,
    token: bytes,
) -> tuple[int, int] | None:
    position = start
    while position < len(data):
        content_end, line_end = _line_end(data, position)
        content = data[position:content_end]
        if content.startswith(token) and not content[len(token) :].strip(b" \t"):
            return position, line_end
        position = line_end
    return None


def _line_end(data: bytes, start: int) -> tuple[int, int]:
    position = start
    while position < len(data) and data[position] not in {10, 13}:
        position += 1
    content_end = position
    if data[position : position + 2] == b"\r\n":
        return content_end, position + 2
    if position < len(data):
        return content_end, position + 1
    return content_end, content_end


def _skip_one_line_ending(data: bytes, position: int) -> int:
    if data[position : position + 2] == b"\r\n":
        return position + 2
    if data[position : position + 1] in {b"\r", b"\n"}:
        return position + 1
    return position


def _remove_one_line_ending(data: bytes, lower_bound: int, position: int) -> int:
    if position - 2 >= lower_bound and data[position - 2 : position] == b"\r\n":
        return position - 2
    if position - 1 >= lower_bound and data[position - 1 : position] in {b"\r", b"\n"}:
        return position - 1
    return position


def parse_wts_component(data: bytes) -> dict[int, str]:
    """Parse WTS and reject headers whose bodies were not fully recovered."""
    return validate_wts_component(data, parse_wts(data))


def validate_wts_component(data: bytes, table: dict[int, str]) -> dict[int, str]:
    """Reject a tolerant WTS result that omitted declared string blocks."""
    expected = {int(match.group(1)) for match in _HEADER.finditer(data)}
    normalized = (
        data.removeprefix(b"\xef\xbb\xbf").replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    )
    if not expected and any(
        line.strip() and not line.lstrip().startswith(b"//")
        for line in normalized.split(b"\n")
    ):
        raise ComponentParseError("missing WTS STRING header")
    missing = expected.difference(table)
    if missing:
        first = min(missing)
        raise ComponentParseError(f"incomplete WTS block: STRING {first}")
    return table


def map_wts_table(md: _MapWtsSource) -> dict[int, str]:
    """Return retained byte-parsed WTS values with text as legacy fallback."""
    if md.ui_strings is not None:
        return dict(md.ui_strings)
    raw = md.scripts.get("war3map.wts") or md.scripts.get("war3campaign.wts")
    if not raw:
        return {}
    try:
        return parse_wts(raw.encode("utf-8", "replace"))
    except UnicodeError, ValueError:
        return {}


def resolve(value: int | float | str, wts: Mapping[int, str]) -> int | float | str:
    """把 'TRIGSTR_390' 这类引用换成实际文本；其它原样返回。"""
    if isinstance(value, str) and value.startswith("TRIGSTR_"):
        try:
            sid = int(value[len("TRIGSTR_") :])
        except ValueError:
            return value
        return wts.get(sid, value)
    return value

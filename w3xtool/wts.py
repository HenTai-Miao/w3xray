"""解析 war3map.wts 字符串表，用于还原 TRIGSTR_n 引用。

格式示例：
    STRING 390
    {
    多行文本
    }
"""
from __future__ import annotations

import re

_HEADER = re.compile(r"STRING\s+(\d+)", re.IGNORECASE)


def parse_wts(data: bytes) -> dict:
    text = data.decode("utf-8-sig", "replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    table: dict[int, str] = {}
    i = 0
    n = len(text)
    while i < n:
        m = _HEADER.search(text, i)
        if not m:
            break
        sid = int(m.group(1))
        brace = text.find("{", m.end())
        if brace < 0:
            break
        end = text.find("}", brace + 1)
        if end < 0:
            break
        body = text[brace + 1:end].strip("\n")
        table[sid] = body
        i = end + 1
    return table


def resolve(value, wts: dict):
    """把 'TRIGSTR_390' 这类引用换成实际文本；其它原样返回。"""
    if isinstance(value, str) and value.startswith("TRIGSTR_"):
        try:
            sid = int(value[len("TRIGSTR_"):])
        except ValueError:
            return value
        return wts.get(sid, value)
    return value

"""解析 war3map.wts 字符串表，用于还原 TRIGSTR_n 引用。

格式示例：
    STRING 390
    {
    多行文本
    }
"""
from __future__ import annotations

import re

_HEADER = re.compile(rb"STRING\s+(\d+)", re.IGNORECASE)


def _decode_str(b: bytes) -> str:
    """单条字符串解码：优先 UTF-8，失败回退 GBK（兼容混合编码的老中文图）。"""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return b.decode("gbk")
        except UnicodeDecodeError:
            return b.decode("utf-8", "replace")


def parse_wts(data: bytes) -> dict:
    # 在字节层解析，按 STRING 块逐条解码：整文件统一解码会让个别 GBK 片段污染成乱码，
    # 且无法再按条恢复；逐条 UTF-8→GBK 回退可兼容 UTF-8 为主、个别 GBK 的混合编码图。
    if data.startswith(b"\xef\xbb\xbf"):          # 去 UTF-8 BOM
        data = data[3:]
    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    table: dict[int, str] = {}
    i = 0
    n = len(data)
    while i < n:
        m = _HEADER.search(data, i)
        if not m:
            break
        sid = int(m.group(1))
        brace = data.find(b"{", m.end())
        if brace < 0:
            break
        end = data.find(b"}", brace + 1)
        if end < 0:
            break
        body = data[brace + 1:end].strip(b"\n")
        table[sid] = _decode_str(body)
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

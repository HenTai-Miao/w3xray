"""解析 war3map.wts 字符串表，用于还原 TRIGSTR_n 引用。

格式示例：
    STRING 390
    {
    多行文本
    }
"""
from __future__ import annotations

import re

from .war3_encoding import decode_warcraft_string

_HEADER = re.compile(rb"STRING\s+(\d+)", re.IGNORECASE)
# 开/闭括号都要求**独占一行**(行首 {/} + 仅尾随空白)：
# - 闭合独占行：避免误伤 GBK 尾字节 0x7D，也避免正文里 "} else {" 这类被当成闭合提前截断。
# - 开括号独占行：避免 STRING 头与正文之间的注释行(如 "// 备注 {x}")里的 { 被当成正文起点。
_OPEN = re.compile(rb"(?m)^\{[ \t]*$")
_CLOSE = re.compile(rb"(?m)^\}[ \t]*$")


def _decode_str(b: bytes) -> str:
    """单条字符串解码：UTF-8 后按系统 ACP/GBK 兼容老中文图。"""
    return decode_warcraft_string(b)


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
        m_open = _OPEN.search(data, m.end())     # 独占一行的 '{'，跳过注释行里的 {
        if m_open:
            brace = m_open.start()
        else:                                     # 兜底：找不到独占行 { 时退回首个 {（不回归旧行为）
            brace = data.find(b"{", m.end())
        if brace < 0:
            break
        m2 = _CLOSE.search(data, brace + 1)      # 行首的 '}'，而非字节流里第一个 '}'
        if not m2:
            break
        body = data[brace + 1:m2.start()].strip(b"\n")
        table[sid] = _decode_str(body)
        i = m2.end()
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

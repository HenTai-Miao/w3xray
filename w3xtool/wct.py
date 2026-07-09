"""war3map.wct 自定义脚本文本解析（移植自 w3x2lni frontend_wct.lua）。

wct 装着地图作者在触发器里手写的自定义 JASS/Lua 片段（一个全局块 + 每个"自定义脚本"
触发器一块）。w3xray 原来只把 wct 原样导出（二进制），解析后能直接读到这些代码。

格式：
  L 版本；若 >1 则该值==0x80000004(重制标记)，再读 L 真版本，断言==1。
  全局块：cstr 注释 + int32 size（==0 空，否则 cstr 代码）。
  触发器块：经典格式 int32 count 后循环；重制格式无 count 读到 EOF。
    每块 u32 size：==0 表示该触发器无代码；否则读 size-1 字节代码 + 跳 1 字节 NUL。
不可信文件：版本不认/截断/size 越界即停，保留已解析部分，绝不抛。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .war3_encoding import decode_warcraft_string


def _decode(b: bytes) -> str:
    return decode_warcraft_string(b)


@dataclass
class WctScript:
    custom_comment: str = ""
    custom_code: str = ""          # 全局自定义脚本
    triggers: list = field(default_factory=list)   # 每个触发器的自定义代码（空串=无）


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def cstr(self) -> str:
        end = self.d.find(b"\x00", self.p)
        if end < 0:
            end = len(self.d)
        s = _decode(self.d[self.p:end])
        self.p = end + 1
        return s

    def raw(self, n: int) -> bytes:
        if self.p + n > len(self.d):
            raise IndexError("raw 越界")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b


def parse_wct(data: bytes) -> WctScript:
    out = WctScript()
    if len(data) < 4:
        return out
    r = _Reader(data)
    try:
        ver = r.u32()
        reforged = False
        if ver > 1:
            if ver != 0x80000004:
                return out
            reforged = True
            ver = r.u32()
        if ver != 1:
            return out
        # 全局自定义脚本
        out.custom_comment = r.cstr()
        size = r.i32()
        out.custom_code = r.cstr() if size != 0 else ""
    except (struct.error, IndexError):
        return out

    # 触发器块：经典有 count，重制读到 EOF
    try:
        count = None if reforged else r.i32()
    except (struct.error, IndexError):
        return out
    idx = 0
    while True:
        if count is not None and idx >= count:
            break
        if r.p >= len(data):
            break
        try:
            size = r.u32()
            if size == 0:
                out.triggers.append("")
            else:
                code = _decode(r.raw(size - 1))
                r.raw(1)               # 跳过结尾 NUL
                out.triggers.append(code)
        except (struct.error, IndexError):
            break
        idx += 1
    return out

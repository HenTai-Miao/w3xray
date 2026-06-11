"""SLK 解析（魔兽 *Data.slk 用的电子表格文本格式）。

SLK 记录：
  ID;...                 头
  B;Y<rows>;X<cols>      维度
  C;X<col>;Y<row>;K<值>  单元格(K 为值；X/Y 可省略沿用)
返回 {行键(第1列值): {列名(第1行值): 值}}。
"""
from __future__ import annotations


def parse_slk(text: str) -> dict:
    cells = {}            # (y, x) -> value
    max_x = max_y = 0
    cur_x = cur_y = 1
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line or line[0] not in "CF":
            continue
        # SLK 用 ;; 转义字段内的字面分号；先换成哨兵再按 ; 拆，拆完还原。
        # （魔兽 Data.slk 多为数值/4cc，几乎不含分号，对真实输入是无操作。）
        rec = [f.replace("\x00", ";") for f in line.replace(";;", "\x00").split(";")]
        kind = rec[0]
        if kind not in ("C", "F"):
            continue
        # C 与 F 记录都可携带 X/Y 来移动光标；F 仅移动光标(不带值)，
        # 随后省略 X/Y 的 C 记录沿用该位置。只有 C 记录的 K 才是单元格的值。
        val = None
        for f in rec[1:]:
            if not f:
                continue
            t, rest = f[0], f[1:]
            if t == "X":
                try:
                    cur_x = int(rest)
                except ValueError:
                    pass
            elif t == "Y":
                try:
                    cur_y = int(rest)
                except ValueError:
                    pass
            elif t == "K" and kind == "C":
                val = rest
        if kind != "C" or val is None:
            continue
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        cells[(cur_y, cur_x)] = val
        max_x = max(max_x, cur_x)
        max_y = max(max_y, cur_y)

    # 第1行=列名，第1列=行键
    headers = {x: cells.get((1, x), "") for x in range(1, max_x + 1)}
    rows = {}
    for y in range(2, max_y + 1):
        key = cells.get((y, 1))
        if not key:
            continue
        row = {}
        for x in range(2, max_x + 1):
            col = headers.get(x)
            v = cells.get((y, x))
            if col and v is not None and v != "":
                row[col] = v
        if row:
            rows[key] = row
    return rows

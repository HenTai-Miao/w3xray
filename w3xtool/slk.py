"""SLK 解析（魔兽 *Data.slk 用的电子表格文本格式）。

SLK 记录：
  ID;...                 头
  B;Y<rows>;X<cols>      维度
  C;X<col>;Y<row>;K<值>  单元格(K 为值；X/Y 可省略沿用)
返回 {行键(第1列值): {列名(第1行值): 值}}。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, override

_MAX_COLUMNS: Final = 4096
_MAX_ROWS: Final = 65536
_MAX_CELLS: Final = 1_000_000


@dataclass(frozen=True, slots=True)
class SlkParseError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def parse_slk(text: str) -> dict[str, dict[str, str]]:
    cells: dict[tuple[int, int], str] = {}
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
                    candidate = int(rest)
                except ValueError as exc:
                    raise SlkParseError(f"invalid SLK column: {rest}") from exc
                else:
                    if not 1 <= candidate <= _MAX_COLUMNS:
                        raise SlkParseError(f"SLK column out of bounds: {candidate}")
                    cur_x = candidate
            elif t == "Y":
                try:
                    candidate = int(rest)
                except ValueError as exc:
                    raise SlkParseError(f"invalid SLK row: {rest}") from exc
                else:
                    if not 1 <= candidate <= _MAX_ROWS:
                        raise SlkParseError(f"SLK row out of bounds: {candidate}")
                    cur_y = candidate
            elif t == "K" and kind == "C":
                val = rest
        if kind != "C" or val is None:
            continue
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        cells[(cur_y, cur_x)] = val
        if len(cells) > _MAX_CELLS:
            raise SlkParseError(f"SLK cell count exceeds {_MAX_CELLS}")

    # 第1行=列名，第1列=行键
    headers = {x: value for (y, x), value in cells.items() if y == 1}
    source_rows: dict[int, dict[int, str]] = {}
    for (y, x), value in cells.items():
        if y > 1:
            source_rows.setdefault(y, {})[x] = value
    rows: dict[str, dict[str, str]] = {}
    for row in source_rows.values():
        key = row.get(1)
        if not key:
            continue
        parsed_row = {}
        for x, value in row.items():
            if x == 1:
                continue
            col = headers.get(x)
            if col and value != "":
                parsed_row[col] = value
        if parsed_row:
            rows[key] = parsed_row
    return rows

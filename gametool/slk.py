"""SLK 解析（魔兽 *Data.slk 用的电子表格文本格式）。

SLK 记录：
  ID;...                 头
  B;Y<rows>;X<cols>      维度
  C;X<col>;Y<row>;K<值>  单元格(K 为值；X/Y 可省略沿用)
返回 {行键(第1列值): {列名(第1行值): 值}}。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from .slk_evidence import parse_slk_evidence


@dataclass(frozen=True, slots=True)
class SlkParseError(ValueError):
    detail: str

    @override
    def __str__(self) -> str:
        return self.detail


def parse_slk(text: str) -> dict[str, dict[str, str]]:
    """Compatibility projection; full source evidence is in parse_slk_evidence.

    Explicitly empty values survive. Conflicts never choose a first/last value;
    unrelated confirmed fields and rows remain usable. Invalid coordinates keep
    the established exception contract for callers requesting this plain view.
    """
    evidence = parse_slk_evidence(text)
    for diagnostic in evidence.diagnostics:
        if diagnostic.code == "invalid_coordinate":
            raise SlkParseError(evidence.diagnostic_text(diagnostic))
    return evidence.as_dict()

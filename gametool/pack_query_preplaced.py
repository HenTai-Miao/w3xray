"""Declared preplaced columns and complete, finite placement records."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import math

from .pack_query_objects import object_category, valid_object_code

_ROLES = (
    ("类型id", "id", "code", "rawcode", "fourcc", "object_id", "对象码"),
    ("名称", "name", "object_name"),
    ("x", "坐标x", "position_x"),
    ("y", "坐标y", "position_y"),
    ("分类", "category", "kind", "对象分类"),
)
_ROLE_NAMES = ("类型ID", "名称", "X", "Y", "分类")
_ROLE_BY_ALIAS = {
    alias: role for role, aliases in enumerate(_ROLES) for alias in aliases
}
_RECOVERY = "请核对表头/完整记录或重新导出；可用 text <词> 查完整原文。"


@dataclass(frozen=True, slots=True)
class PreplacedRecord:
    code: str
    name: str
    point: tuple[float, float]
    category: str | None
    ordinal: int
    raw: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreplacedTable:
    records: tuple[PreplacedRecord, ...]
    diagnostics: tuple[str, ...] = ()


def record_diagnostic(ordinal: int, row: Sequence[str], reason: str) -> str:
    return f"记录 {ordinal}: {reason}；{_RECOVERY} 原始记录: {json.dumps(list(row), ensure_ascii=False)}"


def _legacy(row: Sequence[str]) -> bool:
    return (
        len(row) >= 5
        and row[0].strip().lstrip("+-").isdecimal()
        and valid_object_code(row[1])
    )


def preplaced_table(raw: Sequence[Sequence[str]], *, units: bool) -> PreplacedTable:
    """Resolve unique roles once; never allocate or scan sparse rows to header width."""
    indexed = [
        (ordinal, row)
        for ordinal, row in enumerate(raw, 1)
        if any(cell.strip() for cell in row)
    ]
    if not indexed:
        return PreplacedTable(())
    first = indexed[0][1]
    columns: list[list[int]] = [[] for _ in _ROLES]
    for column, value in enumerate(first):
        role = _ROLE_BY_ALIAS.get(value.strip().casefold())
        if role is not None:
            columns[role].append(column)
    declared = not _legacy(first) and any(columns)
    if declared:
        reasons = [
            f"缺少 {_ROLE_NAMES[role]} 列" for role in (0, 2, 3) if not columns[role]
        ]
        reasons.extend(
            f"重复 {_ROLE_NAMES[role]} 列: "
            + ", ".join(str(column + 1) for column in positions)
            for role, positions in enumerate(columns)
            if len(positions) > 1
        )
        if reasons:
            note = (
                "；".join(reasons)
                + f"；{_RECOVERY} 原始表头: {json.dumps(list(first), ensure_ascii=False)}"
            )
            return PreplacedTable((), (note,))
        slots = tuple(positions[0] if positions else None for positions in columns)
        indexed = indexed[1:]
    else:
        slots = None
    records: list[PreplacedRecord] = []
    notes: list[str] = []
    allowed = ("单位", "英雄", "物品") if units else ("装饰物", "可破坏物")
    for ordinal, row in indexed:
        if slots is None:
            if not _legacy(row) or units and len(row) == 6:
                notes.append(
                    record_diagnostic(
                        ordinal, row, "旧格式列位未确认，未猜测玩家列或坐标列"
                    )
                )
                continue
            x = 4 if units and len(row) >= 7 else 3
            positions = (1, 2, x, x + 1, None)
        else:
            positions = slots

        def missing(role: int) -> bool:
            column = positions[role]
            return column is not None and column >= len(row)

        if any(missing(role) for role in (0, 2, 3)):
            notes.append(record_diagnostic(ordinal, row, "记录缺少表头声明的点位字段"))
            continue

        def cell(role: int) -> str:
            column = positions[role]
            return row[column] if column is not None and column < len(row) else ""

        optional_missing = any(missing(role) for role in (1, 4))
        if optional_missing:
            notes.append(
                record_diagnostic(
                    ordinal, row, "记录缺少声明的名称或分类，保留已确认坐标"
                )
            )

        if not valid_object_code(cell(0)):
            notes.append(record_diagnostic(ordinal, row, "类型ID 不是有效四字节对象码"))
            continue
        try:
            point = (float(cell(2)), float(cell(3)))
        except ValueError, OverflowError:
            point = (math.nan, math.nan)
        if not all(math.isfinite(value) for value in point):
            notes.append(record_diagnostic(ordinal, row, "X/Y 不是已确认的有限数字"))
            continue
        category = object_category(cell(4)) if positions[4] is not None else None
        if category is not None and category not in allowed:
            if not optional_missing:
                notes.append(
                    record_diagnostic(
                        ordinal,
                        row,
                        "声明分类未知或与预放置表类别冲突，保留坐标但未分类",
                    )
                )
            category = ""
        if category == "英雄":
            category = "单位"
        records.append(
            PreplacedRecord(cell(0), cell(1), point, category, ordinal, tuple(row))
        )
    return PreplacedTable(tuple(records), tuple(notes))

"""Declared script-reference columns, complete evidence and exact identities."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .pack_query_objects import valid_object_code

_HEADER = (
    "来源",
    "行号",
    "函数",
    "对象码",
    "10进制",
    "分类",
    "名称",
    "对象来源",
    "上下文",
    "机制",
    "摘要",
    "英文名",
    "细类",
    "源码偏移",
)
_ALIASES = (
    ("来源", "source", "source_file"),
    ("行号", "line", "line_number"),
    ("函数", "function", "function_name"),
    ("对象码", "id", "code", "rawcode", "fourcc"),
    ("10进制", "十进制", "decimal"),
    ("分类", "category", "kind"),
    ("名称", "name", "object_name"),
    ("对象来源", "object_source"),
    ("上下文", "context"),
    ("机制", "mechanism"),
    ("摘要", "summary"),
    ("英文名", "english_name", "name_en"),
    ("细类", "subcategory"),
    ("源码偏移", "source_offset", "offset"),
)
_ROLES = {alias: role for role, aliases in enumerate(_ALIASES) for alias in aliases}
_RENDERED = frozenset((0, 1, 2, 9, 10))
_RECOVERY = "未猜测对象身份，可用 text <词> 查完整原文，或核对表头后重新导出知识包。"


@dataclass(frozen=True, slots=True)
class ReferenceRecord:
    code: str
    category: str
    name: str
    aliases: tuple[str, ...]
    source: str
    line: str
    function: str
    context: str
    mechanism: str
    summary: str
    evidence: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ReferenceIndex:
    records: tuple[ReferenceRecord, ...]
    diagnostics: tuple[str, ...] = ()
    available: bool = True
    readable: bool = True

    @property
    def complete(self) -> bool:
        return self.available and self.readable and not self.diagnostics


def _legacy_record(row: Sequence[str]) -> bool:
    return (
        len(row) >= 4
        and valid_object_code(row[3])
        and (
            row[1].strip().isdecimal()
            or len(row) >= 11
            and row[1].strip().casefold() not in _ALIASES[1]
        )
    )


def reference_index(raw: Sequence[Sequence[str]]) -> ReferenceIndex:
    """Resolve a schema once; visit only cells actually encoded in each record."""
    indexed = [
        (index, row)
        for index, row in enumerate(raw, 1)
        if any(value.strip() for value in row)
    ]
    if not indexed:
        return ReferenceIndex((), available=bool(raw))
    first = indexed[0][1]
    columns: list[list[int]] = [[] for _ in _HEADER]
    for index, value in enumerate(first):
        role = _ROLES.get(value.strip().casefold())
        if role is not None:
            columns[role].append(index)
    declared = not (_legacy_record(first) and first[1].strip().isdecimal()) and (
        bool(columns[3]) or sum(bool(positions) for positions in columns) >= 2
    )
    if declared and _legacy_record(first) and not (columns[0] and columns[1]):
        return ReferenceIndex((), ("首记录的表头/数据边界不明确；" + _RECOVERY,))
    if declared:
        duplicated = [
            f"{name}（第 {', '.join(str(index + 1) for index in positions)} 列）"
            for name, positions in zip(_HEADER, columns)
            if len(positions) > 1
        ]
        reasons = (["缺少对象码列"] if not columns[3] else []) + (
            ["重复语义列: " + "、".join(duplicated)] if duplicated else []
        )
        if reasons:
            return ReferenceIndex((), ("；".join(reasons) + "；" + _RECOVERY,))
        slots = tuple(positions[0] if positions else None for positions in columns)
        rows = indexed[1:]
        names = tuple(first)
    else:
        slots = tuple(range(len(_HEADER)))
        rows = indexed
        names = ()
    counts = Counter(names)
    labels = tuple(
        (name or f"扩展字段{index + 1}")
        + (f" (第{index + 1}列)" if counts[name] > 1 else "")
        for index, name in enumerate(names)
    )
    displayed = {slots[role] for role in _RENDERED if slots[role] is not None}
    records: list[ReferenceRecord] = []
    bad: list[int] = []
    partial: list[int] = []
    for index, row in rows:

        def cell(role: int) -> str:
            column = slots[role]
            return row[column] if column is not None and column < len(row) else ""

        if not valid_object_code(cell(3)) or not declared and not _legacy_record(row):
            bad.append(index)
            continue
        if declared and any(
            column is not None and column >= len(row) for column in slots
        ):
            partial.append(index)
        evidence = tuple(
            (
                labels[column]
                if column < len(labels)
                else _HEADER[column]
                if not declared and column < len(_HEADER)
                else f"扩展字段{column + 1}",
                value,
            )
            for column, value in enumerate(row)
            if column not in displayed
        )
        records.append(
            ReferenceRecord(
                cell(3),
                cell(5),
                cell(6),
                tuple(dict.fromkeys((cell(6), cell(11)))),
                cell(0),
                cell(1),
                cell(2),
                cell(8),
                cell(9),
                cell(10),
                evidence,
            )
        )
    notes: list[str] = []
    if bad:
        notes.append(
            f"有 {len(bad)} 条记录缺少有效四字节对象码或不符合旧格式；记录序号: "
            + ", ".join(map(str, bad))
            + "；"
            + _RECOVERY
        )
    if partial:
        notes.append(
            f"有 {len(partial)} 条记录缺少表头声明的证据字段，保留已确认对象码；记录序号: "
            + ", ".join(map(str, partial))
            + "；"
            + _RECOVERY
        )
    return ReferenceIndex(tuple(records), tuple(notes))

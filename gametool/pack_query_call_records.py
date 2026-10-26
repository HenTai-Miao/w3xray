"""Declared call-index schemas and complete, source-local formula arguments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import re

_HEADER = (
    "来源",
    "行号",
    "函数",
    "调用",
    "参数序号",
    "参数",
    "字符串",
    "对象码",
    "机制",
    "用途",
    "摘要",
    "调用偏移",
)
_ALIASES = (
    ("来源", "source", "source_file"),
    ("行号", "line", "line_number"),
    ("函数", "function", "function_name"),
    ("调用", "call", "api", "call_name"),
    ("参数序号", "argument_index", "argument_position", "position"),
    ("参数", "argument", "argument_text"),
    ("字符串", "string", "string_value"),
    ("对象码", "object_codes", "rawcodes"),
    ("机制", "mechanism"),
    ("用途", "purpose"),
    ("摘要", "summary"),
    ("调用偏移", "call_offset"),
)
_ROLES = {alias: role for role, aliases in enumerate(_ALIASES) for alias in aliases}
_RECOVERY = "未猜测调用参数；可用 text <词> 查完整原文，或核对表头后重新导出知识包。"


@dataclass(frozen=True, slots=True)
class CallRecord:
    row: tuple[str, ...]
    summary: str
    offset: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class CallArgumentIndex:
    records: tuple[CallRecord, ...]
    diagnostics: tuple[str, ...] = ()


def _decimal(value: str) -> bool:
    return bool(value) and value.isascii() and value.isdecimal()


def call_argument_index(raw: Sequence[Sequence[str]]) -> CallArgumentIndex:
    """Normalize only known roles, retaining every encoded extra cell."""
    indexed = [
        (i, row) for i, row in enumerate(raw, 1) if any(value.strip() for value in row)
    ]
    if not indexed:
        return CallArgumentIndex(())
    first = indexed[0][1]
    columns: list[list[int]] = [[] for _ in _HEADER]
    for index, value in enumerate(first):
        role = _ROLES.get(value.strip().casefold())
        if role is not None:
            columns[role].append(index)
    declared = not (len(first) > 1 and _decimal(first[1].strip())) and any(columns)
    if declared:
        duplicate = [
            f"{name}（第 {', '.join(str(i + 1) for i in positions)} 列）"
            for name, positions in zip(_HEADER, columns)
            if len(positions) > 1
        ]
        reasons = ["重复语义列: " + "、".join(duplicate)] if duplicate else []
        if not columns[10] and not all(columns[role] for role in (3, 4, 5)):
            reasons.append("缺少摘要列，且未声明完整的调用/参数序号/参数列")
        if reasons:
            return CallArgumentIndex((), ("；".join(reasons) + "；" + _RECOVERY,))
        slots = tuple(positions[0] if positions else None for positions in columns)
        rows = indexed[1:]
    else:
        slots = ()
        rows = indexed
    records: list[CallRecord] = []
    bad: list[int] = []
    partial: list[int] = []
    invalid_offsets: list[int] = []
    for ordinal, row in rows:
        if declared:
            values = [
                row[index] if index is not None and index < len(row) else ""
                for index in slots
            ]
            used = {index for index in slots if index is not None}
            extra = [value for index, value in enumerate(row) if index not in used]
            if any(index is not None and index >= len(row) for index in slots):
                partial.append(ordinal)
        elif len(row) >= 11:
            values = [*row[:12], *([""] if len(row) == 11 else [])]
            extra = list(row[12:])
        elif len(row) in {1, 4, 5, 6, 10}:
            values = [""] * len(_HEADER)
            if len(row) > 1:
                values[:3] = row[:3]
            if len(row) in {6, 10}:
                values[3:5] = row[3:5]
            if len(row) == 10:
                values[5:9] = row[5:9]
            values[10] = row[-1]
            extra = list(row)
        else:
            bad.append(ordinal)
            continue
        raw_offset = values[11].strip()
        offset = raw_offset.lstrip("0") or "0" if _decimal(raw_offset) else ""
        if raw_offset and not offset:
            invalid_offsets.append(ordinal)
        records.append(
            CallRecord(tuple((*values, *extra)), values[10], offset, ordinal)
        )
    diagnostics: list[str] = []
    for indices, reason in (
        (bad, "不符合已知调用索引格式"),
        (partial, "缺少表头声明字段，已保留可读证据"),
        (invalid_offsets, "调用偏移不是非负十进制数，未用其合并调用"),
    ):
        if indices:
            diagnostics.append(
                f"有 {len(indices)} 条记录{reason}；记录序号: "
                + ", ".join(map(str, indices))
                + "；"
                + _RECOVERY
            )
    return CallArgumentIndex(tuple(records), tuple(diagnostics))


@dataclass
class _Arguments:
    source: str
    offset: str
    values: dict[str, str] = field(default_factory=dict)
    owners: set[str] = field(default_factory=set)
    records: list[int] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def formula_argument_groups(
    index: CallArgumentIndex,
) -> tuple[list[tuple[str, ...]], tuple[str, ...]]:
    """Use explicit call offsets for shuffled rows; never allocate from a position."""
    groups: list[_Arguments] = []
    by_offset: dict[tuple[str, str], _Arguments] = {}
    previous: tuple[str, ...] = ()
    current: _Arguments | None = None
    for record in index.records:
        row = record.row
        if row[3].removeprefix("_G.") != "YDWENewItemsFormula" or not row[4]:
            previous, current = (), None
            continue
        position = row[4].lstrip("0") if _decimal(row[4]) else ""
        if record.offset:
            previous, current = (), None
            key = (row[0], record.offset)
            group = by_offset.get(key)
            if group is None:
                group = by_offset[key] = _Arguments(*key)
                groups.append(group)
        else:
            identity = (*row[:4], record.summary)
            if current is None or identity != previous or position == "1":
                current = _Arguments(row[0], "")
                groups.append(current)
            previous, group = identity, current
            if position != str(len(group.values) + 1):
                group.problems.append("无偏移旧记录的参数顺序不连续，未跨记录猜测调用")
        group.records.append(record.ordinal)
        if row[2]:
            group.owners.add(row[2])
        if not position:
            group.problems.append("无效参数序号: " + row[4])
            continue
        value = row[5]
        if not value.rstrip().endswith("'"):
            value = re.sub(r"^(\s*)'(?=[+-])", r"\1", value)
        if position in group.values and group.values[position] != value:
            group.problems.append(
                f"参数 {position} 的值冲突: {group.values[position]} / {value}"
            )
        else:
            group.values[position] = value
    for record in index.records:
        group = by_offset.get((record.row[0], record.offset)) if record.offset else None
        if (
            group is not None
            and record.row[3]
            and record.row[3].removeprefix("_G.") != "YDWENewItemsFormula"
        ):
            group.records.append(record.ordinal)
            group.problems.append("同一调用偏移的调用名称不一致: " + record.row[3])
    result: list[tuple[str, ...]] = []
    diagnostics: list[str] = []
    for group in groups:
        if len(group.owners) > 1:
            group.problems.append(
                "调用所属函数不一致: " + ", ".join(sorted(group.owners))
            )
        ordered = tuple(str(i) for i in range(1, len(group.values) + 1))
        if not ordered or any(position not in group.values for position in ordered):
            group.problems.append("参数序号不连续，不能确认完整配方")
        if group.problems:
            diagnostics.append(
                f"来源 {group.source or '未记录'} / 调用偏移 {group.offset or '未记录'} / 记录序号: "
                + ", ".join(map(str, group.records))
                + "；"
                + "；".join(dict.fromkeys(group.problems))
                + "；"
                + _RECOVERY
            )
        else:
            result.append(tuple(group.values[position] for position in ordered))
    return result, tuple(diagnostics)

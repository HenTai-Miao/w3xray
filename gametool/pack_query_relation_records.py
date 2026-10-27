"""Declared acquisition columns with lossless rows and source diagnostics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
import json
from typing import overload

from .batch_tsv import decode_tsv_cell
from .item_relation_exports import ACQUISITION_REPORT_HEADER
from .item_relation_models import (
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
)
from .pack_query_objects import valid_object_code
from .object_codes import unquote_legacy_object_code

_ALIASES = (
    ("关系id", "relation_id"),
    ("地图子图", "map", "map_name", "submap"),
    ("关系类型", "关系", "relation_type", "kind"),
    ("装备id", "成品id", "物品id", "对象id", "item_id", "product_id"),
    ("装备名称", "成品名称", "物品名称", "物品名", "item_name", "product_name"),
    ("来源分类", "来源类型", "来源类别", "source_category"),
    ("来源id", "source_id"),
    ("来源名称", "source_name"),
    ("实例序号", "instance_serial", "serial"),
    ("玩家", "player"),
    ("x",),
    ("y",),
    ("z",),
    ("掉落组", "drop_group", "group_index"),
    ("组内序号", "entry_index"),
    ("概率", "chance", "probability"),
    ("槽位", "slot"),
    ("合成材料id", "材料id", "material_ids"),
    ("合成材料名称与数量", "材料名称与数量", "materials", "material_text"),
    ("证据文件", "evidence_file", "source_file"),
    ("证据函数/触发", "evidence_function", "function", "trigger"),
    ("证据行号/偏移", "evidence_position", "location"),
    ("原始证据", "raw_evidence", "evidence"),
    ("可信度", "confidence"),
    ("完整性", "completeness"),
    ("未解析原因", "unresolved_reason", "reason"),
    ("装备英文名", "item_english_name", "item_name_en"),
    ("装备细类", "item_subcategory"),
)
_ROLES = {alias: role for role, aliases in enumerate(_ALIASES) for alias in aliases}
_KINDS = {kind.name.casefold(): kind.value for kind in ItemRelationKind}
_KIND_VALUES = frozenset(kind.value for kind in ItemRelationKind)
_STATE_LABELS = {
    23: {value.name.casefold(): value.value for value in RelationConfidence},
    24: {value.name.casefold(): value.value for value in RelationCompleteness},
}
_RECOVERY = "未猜测关系身份；可用 drop <码> / text <词> 查完整原文，或核对表头后重新导出知识包。"
_DISPLAYED = frozenset((2, 3, 5, 6, 23, 24, 25))


@dataclass(frozen=True, slots=True)
class AcquisitionRecord(Sequence[str]):
    values: tuple[str, ...]
    raw: tuple[str, ...]
    ordinal: int
    extensions: tuple[tuple[str, str], ...]
    evidence: tuple[tuple[str, str], ...]

    @overload
    def __getitem__(self, index: int) -> str: ...
    @overload
    def __getitem__(self, index: slice) -> tuple[str, ...]: ...
    def __getitem__(self, index: int | slice) -> str | tuple[str, ...]:
        return self.values[index]

    def __len__(self) -> int:
        return len(self.values)


@dataclass(frozen=True, slots=True)
class AcquisitionIndex:
    records: tuple[AcquisitionRecord, ...]
    diagnostics: tuple[str, ...] = ()
    roles: frozenset[int] = frozenset()
    diagnostic_ordinals: tuple[int, ...] = ()


def _diagnostic(ordinal: int, raw: Sequence[str], reason: str) -> str:
    return f"记录 {ordinal}: {reason}；原始记录: {json.dumps(tuple(raw), ensure_ascii=False)}；{_RECOVERY}"


@lru_cache(maxsize=8)
def acquisition_index(raw: tuple[tuple[str, ...], ...]) -> AcquisitionIndex:
    """Resolve roles once; visit encoded cells without padding to header width."""
    indexed = [
        (i, row) for i, row in enumerate(raw, 1) if any(value.strip() for value in row)
    ]
    if not indexed:
        return AcquisitionIndex(())
    first = tuple(decode_tsv_cell(value) for value in indexed[0][1])
    columns: list[list[int]] = [[] for _ in _ALIASES]
    for i, value in enumerate(first):
        role = _ROLES.get(value.strip().casefold())
        if role is not None:
            columns[role].append(i)
    legacy = first[2].strip().casefold() not in _ALIASES[2] if len(first) > 2 else False
    legacy = legacy and (
        len(first) >= 4
        and bool(first[2])
        and (
            valid_object_code(unquote_legacy_object_code(first[3]))
            or first[2] in _KIND_VALUES
        )
    )
    declared = not legacy and (
        bool(columns[2] or columns[3]) or sum(bool(c) for c in columns) >= 2
    )
    if declared:
        reasons = [
            f"缺少{ACQUISITION_REPORT_HEADER[role]}列"
            for role in (2, 3)
            if not columns[role]
        ]
        duplicate = [
            ACQUISITION_REPORT_HEADER[role]
            + "（第 "
            + ", ".join(str(i + 1) for i in positions)
            + " 列）"
            for role, positions in enumerate(columns)
            if len(positions) > 1
        ]
        if duplicate:
            reasons.append("重复语义列: " + "、".join(duplicate))
        if reasons:
            reason = "；".join(reasons)
            return AcquisitionIndex(
                (),
                (
                    _diagnostic(indexed[0][0], indexed[0][1], reason),
                    *(
                        _diagnostic(i, row, "表头不明确，保留未分类证据")
                        for i, row in indexed[1:]
                    ),
                ),
                diagnostic_ordinals=tuple(i for i, _row in indexed),
            )
        prefix = (
            len(first) in (20, 26, 28)
            and first == ACQUISITION_REPORT_HEADER[: len(first)]
        )
        slots = tuple(
            positions[0]
            if positions
            else role
            if prefix and role >= len(first)
            else None
            for role, positions in enumerate(columns)
        )
        rows, names = indexed[1:], first
    else:
        slots = tuple(range(len(_ALIASES)))
        rows, names = indexed, ()
    roles = frozenset(
        role for role, position in enumerate(slots) if position is not None
    )
    positions = {
        position: role for role, position in enumerate(slots) if position is not None
    }
    records: list[AcquisitionRecord] = []
    diagnostics: list[str] = []
    diagnostic_ordinals: list[int] = []
    for ordinal, row in rows:
        values = [
            decode_tsv_cell(row[i]) if i is not None and i < len(row) else ""
            for i in slots
        ]
        for column in (3, 6):
            values[column] = unquote_legacy_object_code(values[column])
        values[2] = _KINDS.get(values[2].strip().casefold(), values[2].strip())
        for column, labels in _STATE_LABELS.items():
            values[column] = labels.get(
                values[column].strip().casefold(), values[column].strip()
            )
        missing = (
            [
                ACQUISITION_REPORT_HEADER[role]
                for role, position in enumerate(slots)
                if position is not None
                and position < len(names)
                and position >= len(row)
            ]
            if declared
            else []
        )
        if not values[2] or not valid_object_code(values[3]):
            diagnostic_ordinals.append(ordinal)
            diagnostics.append(
                _diagnostic(
                    ordinal, row, "关系类型缺失或装备/物品 ID 不是有效四字节对象码"
                )
            )
            continue
        if missing:
            diagnostic_ordinals.append(ordinal)
            diagnostics.append(
                _diagnostic(
                    ordinal,
                    row,
                    "缺少表头声明字段，保留已确认关系: " + "、".join(missing),
                )
            )
        extensions: list[tuple[str, str]] = []
        evidence: list[tuple[str, str]] = []
        for i, value in enumerate(row):
            role = positions.get(i)
            label = (
                names[i]
                if i < len(names)
                else ACQUISITION_REPORT_HEADER[role]
                if role is not None
                else f"扩展列{i + 1}"
            )
            if role is None:
                extensions.append((label, value))
                evidence.append((label, value))
            elif role not in _DISPLAYED and value:
                evidence.append((label, value))
        records.append(
            AcquisitionRecord(
                tuple(values), row, ordinal, tuple(extensions), tuple(evidence)
            )
        )
    return AcquisitionIndex(
        tuple(records), tuple(diagnostics), roles, tuple(diagnostic_ordinals)
    )


def raw_relation(row: Sequence[str]) -> Sequence[str]:
    return row.raw if isinstance(row, AcquisitionRecord) else row


def relation_evidence(row: Sequence[str]) -> str:
    """Keep complete encoded provenance and extension fields of selected records."""
    if not isinstance(row, AcquisitionRecord) or not row.evidence:
        return ""
    return " 证据字段: " + json.dumps(row.evidence, ensure_ascii=False)

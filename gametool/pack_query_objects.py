"""Complete, header-aware object tables shared by every knowledge-pack consumer."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

from .batch_tsv import decode_tsv_cell
from .object_codes import unquote_legacy_object_code, valid_object_code

OBJECT_TABLES = ("物品", "单位", "技能", "英雄", "增益", "科技", "装饰物", "可破坏物")
_HEADER = ("分类", "ID", "数值", "基础ID", "名称", "自定义", "说明")
_ALIASES = (
    {"分类", "category"},
    {"id", "四码", "rawcode", "fourcc", "类型id"},
    {"数值", "10进制", "十进制", "decimal"},
    {"基础id", "baseid", "base_id", "四码2"},
    {"名称", "name"},
    {"自定义", "custom", "is_custom"},
    {"说明", "描述", "description"},
)
_FIELD_HEADER = ("分类", "ID", "名称", "字段键", "字段名", "值", "来源")
_FIELD_ALIASES = (
    _ALIASES[0],
    _ALIASES[1],
    {"名称", "name", "对象名", "object_name"},
    {"字段键", "字段", "field_key", "fieldkey", "key"},
    {"字段名", "field_label", "fieldlabel", "label"},
    {"值", "value"},
    {"来源", "source"},
)
_CATEGORIES = {
    **dict.fromkeys(("item", "items"), "物品"),
    **dict.fromkeys(("unit", "units"), "单位"),
    **dict.fromkeys(("skill", "skills", "ability", "abilities"), "技能"),
    **dict.fromkeys(("hero", "heroes"), "英雄"),
    **dict.fromkeys(("buff", "buffs"), "增益"),
    **dict.fromkeys(("tech", "upgrade", "upgrades"), "科技"),
    **dict.fromkeys(("doodad", "doodads"), "装饰物"),
    **dict.fromkeys(
        ("destructable", "destructables", "destructible", "destructibles"), "可破坏物"
    ),
}
_KNOWN_CATEGORIES = frozenset(_CATEGORIES.values())


def object_category(value: str) -> str:
    """Normalize a declared category without inferring it from an object code."""
    raw = value.strip()
    return _CATEGORIES.get(raw.casefold(), raw)


@dataclass(frozen=True, slots=True)
class ObjectTable:
    rows: tuple[tuple[str, ...], ...]
    diagnostics: tuple[str, ...] = ()
    readable: bool = True

    @property
    def complete(self) -> bool:
        return self.readable and not self.diagnostics


@lru_cache(maxsize=8)
def object_table(category: str, raw: tuple[tuple[str, ...], ...]) -> ObjectTable:
    """Canonicalize declared columns; headerless records keep their first object."""
    return _table(category, raw, fields=False)


@lru_cache(maxsize=8)
def object_field_table(raw: tuple[tuple[str, ...], ...]) -> ObjectTable:
    """Preserve field evidence with explicit category, ID, key and value columns."""
    return _table("", raw, fields=True)


def _table(
    category: str, raw: tuple[tuple[str, ...], ...], *, fields: bool
) -> ObjectTable:
    category = object_category(category)
    header = _FIELD_HEADER if fields else _HEADER
    aliases = _FIELD_ALIASES if fields else _ALIASES
    required = (0, 1, 3, 5) if fields else (1, 4)

    def valid_category(value: str) -> bool:
        declared = object_category(value)
        return declared in _KNOWN_CATEGORIES if fields else declared == category

    def legacy_record(row: tuple[str, ...]) -> bool:
        return (
            len(row) >= (6 if fields else 5)
            and valid_category(row[0])
            and valid_object_code(unquote_legacy_object_code(row[1]))
        )

    indexed = [
        (index, tuple(decode_tsv_cell(value) for value in row))
        for index, row in enumerate(raw, 1)
        if any(value.strip().lstrip("\ufeff").strip() for value in row)
    ]
    if not indexed:
        return ObjectTable((header,))
    first = indexed[0][1]
    legacy = legacy_record(first)
    names = tuple(value.strip().lstrip("\ufeff").strip() for value in first)
    normalized = tuple(value.casefold() for value in names)
    columns = [
        tuple(index for index, name in enumerate(normalized) if name in choices)
        for choices in aliases
    ]
    if not columns[0] and names and valid_category(names[0]):
        columns[0] = (0,)
    evidence_columns = columns[3] and columns[5] if fields else columns[4]
    if legacy and columns[1] and evidence_columns:
        if not fields and (columns[2] or columns[3]):
            legacy = False
        else:
            return ObjectTable(
                (header,),
                (
                    "首记录同时符合表头和无表头数据形态；未猜测对象身份，请添加明确的"
                    + "/".join(header[index] for index in required)
                    + "表头。",
                ),
            )
    if not legacy and (columns[1] or evidence_columns):
        missing = [header[index] for index in required if not columns[index]]
        duplicated = [
            f"{name}（第 {', '.join(str(index + 1) for index in positions)} 列）"
            for name, positions in zip(header, columns)
            if len(positions) > 1
        ]
        if missing or duplicated:
            reason = "; ".join(
                filter(
                    None,
                    (
                        "缺少列: " + "、".join(missing) if missing else "",
                        "重复语义列: " + "、".join(duplicated) if duplicated else "",
                    ),
                )
            )
            return ObjectTable(
                (header,), (reason + "；未猜测列身份，请核对表头或重新导出知识包。",)
            )
        slots = tuple(positions[0] if positions else None for positions in columns)
        records = indexed[1:]
        source_names = names
    else:
        if not legacy and not any(legacy_record(row) for _index, row in indexed):
            return ObjectTable(
                (header,),
                (
                    "缺少可识别的 "
                    + "/".join(header[index] for index in required)
                    + "表头，且不符合无表头旧格式；请核对表头或重新导出知识包。",
                ),
            )
        slots = tuple(range(7))
        records = indexed
        source_names = ()
    width = max((len(row) for _index, row in records), default=len(source_names))
    width = max(width, len(source_names))
    used = {index for index in slots if index is not None}
    extras = tuple(index for index in range(width) if index not in used)
    counts = Counter(source_names)
    labels = tuple(
        (
            source_names[index]
            if counts[source_names[index]] == 1
            else f"{source_names[index]} (第{index + 1}列)"
        )
        if index < len(source_names) and source_names[index]
        else f"扩展字段{index + 1}"
        for index in extras
    )
    label_counts = Counter((*header, *labels))
    unique_labels: list[str] = []
    seen: set[str] = set(header)
    for index, label in zip(extras, labels):
        if label_counts[label] > 1:
            label += f" (原列{index + 1})"
        while label in seen:
            label += f" (原列{index + 1})"
        seen.add(label)
        unique_labels.append(label)
    labels = tuple(unique_labels)
    rows: list[tuple[str, ...]] = [(*header, *labels)]
    bad: list[int] = []
    for index, row in records:

        def cell(column: int | None) -> str:
            value = row[column] if column is not None and column < len(row) else ""
            return (
                unquote_legacy_object_code(value)
                if column == slots[1] or not fields and column == slots[3]
                else value
            )

        code = cell(slots[1])
        declared_category = object_category(cell(slots[0]))
        if (
            not valid_object_code(code)
            or any(
                column is None or column >= len(row)
                for column in (slots[i] for i in required)
            )
            or (
                declared_category not in _KNOWN_CATEGORIES
                if fields
                else bool(declared_category) and declared_category != category
            )
        ):
            bad.append(index)
            continue
        values = tuple(cell(column) for column in slots)
        encoded_extras = extras[: bisect_left(extras, len(row))]
        rows.append(
            (
                declared_category if fields else category,
                *values[1:],
                *(row[column] for column in encoded_extras),
            )
        )
    notes = (
        (
            f"{'对象字段表' if fields else '对象表'}有 {len(bad)} 行字段不完整或不是四字节对象码，或分类不符；记录序号: "
            + ", ".join(map(str, bad))
            + "；请核对知识包或重新导出。",
        )
        if bad
        else ()
    )
    return ObjectTable(tuple(rows), notes)

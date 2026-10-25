"""Complete, header-aware object tables shared by every knowledge-pack consumer."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

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


def _category(value: str) -> str:
    raw = value.strip()
    return _CATEGORIES.get(raw.casefold(), raw)


def valid_object_code(code: str) -> bool:
    return len(code) == 4 and all(ord(char) <= 255 for char in code)


@dataclass(frozen=True, slots=True)
class ObjectTable:
    rows: tuple[tuple[str, ...], ...]
    diagnostics: tuple[str, ...] = ()


@lru_cache(maxsize=8)
def object_table(category: str, raw: tuple[tuple[str, ...], ...]) -> ObjectTable:
    """Canonicalize declared columns; headerless records keep their first object."""
    category = _category(category)
    indexed = [
        (index, row)
        for index, row in enumerate(raw, 1)
        if any(value.lstrip("\ufeff").strip() for value in row)
    ]
    if not indexed:
        return ObjectTable((_HEADER,))
    first = indexed[0][1]
    legacy = (
        len(first) >= 5
        and _category(first[0]) == category
        and valid_object_code(first[1])
    )
    names = tuple(value.lstrip("\ufeff").strip() for value in first)
    normalized = tuple(value.casefold() for value in names)
    columns = [
        tuple(index for index, name in enumerate(normalized) if name in aliases)
        for aliases in _ALIASES
    ]
    if not columns[0] and names and _category(names[0]) == category:
        columns[0] = (0,)
    if legacy and columns[1] and columns[4]:
        if columns[2] or columns[3]:
            legacy = False
        else:
            return ObjectTable(
                (_HEADER,),
                (
                    "首记录同时符合表头和无表头数据形态；未猜测对象身份，请添加明确的分类/ID/名称表头。",
                ),
            )
    if not legacy and (columns[1] or columns[4]):
        missing = [
            name
            for name, positions in zip(_HEADER, columns)
            if name in {"ID", "名称"} and not positions
        ]
        duplicated = [
            f"{name}（第 {', '.join(str(index + 1) for index in positions)} 列）"
            for name, positions in zip(_HEADER, columns)
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
                (_HEADER,), (reason + "；未猜测列身份，请核对表头或重新导出知识包。",)
            )
        slots = tuple(positions[0] if positions else None for positions in columns)
        records = indexed[1:]
        source_names = names
    else:
        if not legacy and not any(
            len(row) >= 5
            and _category(row[0]) == category
            and valid_object_code(row[1])
            for _index, row in indexed
        ):
            return ObjectTable(
                (_HEADER,),
                (
                    "缺少可识别的 ID/名称表头，且不符合无表头旧格式；请核对表头或重新导出知识包。",
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
    label_counts = Counter((*_HEADER, *labels))
    unique_labels: list[str] = []
    seen: set[str] = set(_HEADER)
    for index, label in zip(extras, labels):
        if label_counts[label] > 1:
            label += f" (原列{index + 1})"
        while label in seen:
            label += f" (原列{index + 1})"
        seen.add(label)
        unique_labels.append(label)
    labels = tuple(unique_labels)
    rows: list[tuple[str, ...]] = [(*_HEADER, *labels)]
    bad: list[int] = []
    for index, row in records:

        def cell(column: int | None) -> str:
            return row[column] if column is not None and column < len(row) else ""

        code = cell(slots[1])
        name_column = slots[4]
        declared_category = _category(cell(slots[0]))
        if (
            not valid_object_code(code)
            or name_column is None
            or name_column >= len(row)
            or declared_category
            and declared_category != category
        ):
            bad.append(index)
            continue
        values = tuple(cell(column) for column in slots)
        encoded_extras = extras[: bisect_left(extras, len(row))]
        rows.append(
            (
                category,
                *values[1:],
                *(row[column] for column in encoded_extras),
            )
        )
    notes = (
        (
            f"对象表有 {len(bad)} 行字段不完整或不是四字节对象码，或分类不符；记录序号: "
            + ", ".join(map(str, bad))
            + "；请核对知识包或重新导出。",
        )
        if bad
        else ()
    )
    return ObjectTable(tuple(rows), notes)

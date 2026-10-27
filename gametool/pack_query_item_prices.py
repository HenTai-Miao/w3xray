"""Qualified item gold evidence shared by price, item and shop queries."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .pack_query_field_evidence import ObjectField
from .pack_query_numeric_values import decimal_value, numeric_text
from .pack_query_object_details import (
    ObjectDetailIndex,
    ObjectDetailSources,
    ObjectRecord,
    load_object_records,
    render_object_record,
)
from .pack_query_objects import valid_object_code
from .search import compile_query

_GOLD_KEYS = frozenset(("igol", "goldcost"))
_STATIC_NOTE = "  静态金币字段只说明对象估值；商店出售关系与运行时成交价需独立证据。"


class ItemPriceSources(ObjectDetailSources, Protocol):
    def _base_prices(self) -> dict[str, str]: ...


@dataclass(frozen=True, slots=True)
class ItemPrice:
    code: str
    value: str = ""
    origin: str = "金币字段未记录"
    fields: tuple[ObjectField, ...] = ()
    overridden: tuple[ObjectField, ...] = ()
    custom: bool = False
    bases: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return bool(self.fields or self.value or self.diagnostics)

    def summary(self) -> str:
        return (self.value or "未确认") + " (" + self.origin + ")"

    def detail_lines(self, *, include_fields: bool = False) -> tuple[str, ...]:
        lines = [_STATIC_NOTE]
        lines.extend("  " + note for note in self.diagnostics)
        if self.overridden:
            lines.append("  以下继承记录已被自定义金币字段覆盖，完整原文仍保留。")
        if include_fields:
            for field in (*self.fields, *self.overridden):
                lines.extend(field.render_lines())
        if not self.value:
            lines.append(
                f"  金币字段未确认；可用 item {self.code} / text {self.code} 查证或重新导出，未据此判定非卖品。"
            )
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class ItemPriceIndex:
    objects: ObjectDetailIndex
    prices: dict[str, ItemPrice]
    names: dict[str, tuple[str, ...]]

    def for_code(self, code: str) -> ItemPrice:
        return self.prices.get(code, ItemPrice(code))

    def name_for(self, code: str) -> str:
        return " / ".join(self.names.get(code, ())) or code


def _field_value(fields: tuple[ObjectField, ...]) -> tuple[str, tuple[str, ...]]:
    values = tuple(decimal_value(field.value) for field in fields)
    if any(value is None for value in values) or len(set(values)) != 1:
        message = (
            "金币字段冲突，未选择最后一条或继承值。"
            if len(set(values)) > 1
            else "金币字段未确认，原文不是有限数字；未回退其他值。"
        )
        return "", (message,)
    return numeric_text(fields[0].value), ()


def item_price_index(
    objects: ObjectDetailIndex,
    base_prices: Mapping[str, str],
    sources: ObjectDetailSources,
) -> ItemPriceIndex:
    grouped: dict[str, list[ObjectRecord]] = {}
    for record in objects.records:
        grouped.setdefault(record.row[1], []).append(record)
    prices: dict[str, ItemPrice] = {}
    names: dict[str, tuple[str, ...]] = {}
    for code, records in grouped.items():
        names[code] = tuple(
            dict.fromkeys(
                sources._clean(record.row[4])
                for record in records
                if sources._clean(record.row[4])
            )
        )
        fields = tuple(
            dict.fromkeys(
                field
                for evidence in {
                    id(record.evidence): record.evidence for record in records
                }.values()
                for field in evidence.fields
            )
        )
        custom = tuple(field for field in fields if field.key.casefold() in _GOLD_KEYS)
        inherited = tuple(
            field
            for field in fields
            if field.key.casefold().startswith("base:")
            and field.key.casefold()[5:] in _GOLD_KEYS
        )
        bases = tuple(
            dict.fromkeys(record.row[3] for record in records if not record.from_fields)
        )
        selected = custom or inherited
        if selected:
            value, notes = _field_value(selected)
            origin = "地图价" if custom else "继承字段"
            prices[code] = ItemPrice(
                code,
                value,
                origin,
                selected,
                inherited if custom else (),
                bool(custom),
                bases,
                notes,
            )
            continue
        notes: tuple[str, ...] = ()
        value, origin = "", "金币字段未记录"
        if len(bases) > 1:
            notes = (
                "基础 ID 声明冲突，金币字段未确认；保留全部基础 ID: "
                + " / ".join(repr(base) for base in bases),
            )
        elif not objects.field_view.complete:
            notes = (
                "金币字段来源不完整，无法确认自定义覆写；未以基础资料替代缺失证据。",
            )
        elif len(bases) == 1 and valid_object_code(bases[0]):
            raw = base_prices.get(bases[0], "")
            if decimal_value(raw) is not None:
                value, origin = numeric_text(raw), "继承基础 " + bases[0]
        prices[code] = ItemPrice(code, value, origin, bases=bases, diagnostics=notes)
    return ItemPriceIndex(objects, prices, names)


def load_item_price_index(pack: Path, sources: ItemPriceSources) -> ItemPriceIndex:
    return item_price_index(
        load_object_records(pack, "物品", sources), sources._base_prices(), sources
    )


def query_item_prices(
    pack: Path, query: str, limit: int, sources: ItemPriceSources
) -> list[str]:
    expression = sources._clean(query).strip()
    compiled = compile_query(expression)
    if expression and compiled.is_empty:
        return [
            "未找到物品价格: 查询表达式没有关键词",
            "可用名称、四码、说明或完整字段词，用 &&、|| 组合查询。",
        ]
    index = load_item_price_index(pack, sources)
    matches = [
        record
        for record in index.objects.records
        if not expression
        or compiled.score_fields(record.search_fields(sources)) is not None
    ]
    reference: list[str] = []
    if (
        valid_object_code(expression)
        and not any(
            record.row[1].casefold() == expression.casefold()
            for record in index.objects.records
        )
        and (price := sources._base_prices().get(expression.lower()))
    ):
        reference = [
            f"基础物品 [{expression.lower()}]  金币: {price}（基础资料参考）",
            "  该资料未证明本图使用此物品或存在商店出售；请用 item / shop / where 核对地图证据。",
            _STATIC_NOTE,
        ]
    if not matches:
        if reference:
            return reference
        return [
            "未找到物品价格: " + query,
            f"  本次可确认物品对象共 {len(index.objects.records)} 件；可换名称、四码或字段词，用 search <词> 跨八表查。",
            "  数据来源: 对象ID/物品.tsv、对象字段.tsv 与明确基础 ID 的基础资料；可用 text <词> 查原文或重新导出。",
            "  若有坐标，可用 near <x> <y> 反查附近对象。",
        ]
    lines: list[str] = []
    for record in matches[:limit] if limit else matches:
        details = render_object_record(
            record, index.objects.view, sources, include_description=False
        )
        price = index.for_code(record.row[1])
        lines.append(details[0])
        lines.append("  金币: " + price.summary())
        lines.extend(price.detail_lines())
        if description := sources._clean(record.row[6]):
            lines.append("  ID表说明（原始清单证据）: " + description)
        lines.extend(details[1:])
    if limit and len(matches) > limit:
        lines.append(
            f"  (已达 --limit {limit}, 其余 {len(matches) - limit} 条未显示——去掉 --limit 看全量)"
        )
    if not index.objects.complete:
        lines.append("  数据源有诊断，以上为已确认物品记录；记录数不代表完整地图总量。")
    lines.extend(reference)
    return lines

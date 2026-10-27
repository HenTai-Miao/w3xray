"""Complete item queries over item records and selected linked-ability evidence."""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from .pack_query_item_abilities import AbilityEvidence, ItemAbilityIndex
from .pack_query_item_prices import ItemPriceSources, item_price_index
from .pack_query_object_details import (
    ObjectRecord,
    load_object_records,
    render_object_record,
)
from .search import compile_query


class ItemDetailSources(ItemPriceSources, Protocol):
    def load_item_tooltips(self, pack: Path) -> dict[str, str]: ...
    def _load_item_ability_evidence(self, pack: Path) -> ItemAbilityIndex: ...


def _ability_search_fields(
    ability: AbilityEvidence, sources: ItemDetailSources
) -> tuple[str, ...]:
    def fields() -> Iterator[str]:
        yield ability.code
        yield from ability.names
        for field in ability.fields:
            yield from field.search_fields(sources._clean)

    return tuple(fields())


def query_item_details(
    pack: Path, query: str, limit: int, sources: ItemDetailSources
) -> list[str]:
    expression = sources._clean(query).strip()
    compiled = compile_query(expression)
    if expression and compiled.is_empty:
        return [
            "未找到物品: 查询表达式没有关键词",
            '可输入名称、四码、字段词；组合使用 &&、||、%、括号或 ="精准词"。',
        ]
    index = load_object_records(pack, "物品", sources)
    abilities = sources._load_item_ability_evidence(pack)
    ability_fields: dict[str, tuple[str, ...]] = {}

    def search_fields(record: ObjectRecord) -> Iterator[str]:
        yield from record.search_fields(sources)
        for ability in abilities.abilities_for(record.row[1]):
            if ability.code not in ability_fields:
                ability_fields[ability.code] = _ability_search_fields(ability, sources)
            yield from ability_fields[ability.code]

    matches = [
        record
        for record in index.records
        if not expression or compiled.score_fields(search_fields(record)) is not None
    ]
    if not matches:
        return [
            "未找到物品: " + query,
            f"  本次可确认物品对象记录共 {len(index.records)} 件；可换名称、四码、说明或字段关键词，用 search <词> 跨八表查。",
            "  数据来源: 对象ID/物品.tsv、对象字段.tsv 及携带技能字段；缺失时请重新导出，可用 text <词> 查其他文本。",
            "  若有坐标，可用 near <x> <y> 反查附近对象。",
            *(
                ["  数据源有诊断，当前已确认记录数不代表完整地图总量。"]
                if not index.complete
                else []
            ),
        ]
    prices = item_price_index(index, sources._base_prices(), sources)
    tooltips = sources.load_item_tooltips(pack)
    output: list[str] = []
    for record in matches[:limit] if limit else matches:
        code = record.row[1]
        details = render_object_record(
            record, index.view, sources, include_description=False
        )
        output.append(details[0])
        price = prices.for_code(code)
        if price.has_evidence:
            output.append("  金币: " + price.summary())
            output.extend(price.detail_lines())
        if effects := abilities.summaries_for(code):
            output.append("  属性字段摘要: " + ", ".join(effects))
        if tooltip := tooltips.get(code):
            output.append("  地图说明: " + tooltip)
        if note := sources._clean(record.row[6]):
            output.append("  ID表说明（原始清单证据）: " + note)
        output.extend(abilities.render_item(code))
        output.extend(details[1:])
    if limit and len(matches) > limit:
        output.append(
            f"  (已达 --limit {limit}, 其余 {len(matches) - limit} 条未显示——去掉 --limit 看全量)"
        )
    if not index.complete:
        output.append("  数据源有诊断，以上为已确认物品记录；完整性边界见来源诊断。")
    return output

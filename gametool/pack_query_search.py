"""Complete, scoped object-text search using the shared Boolean query language."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Protocol

from .search import compile_query
from .pack_query_objects import OBJECT_TABLES, object_category
from .pack_query_object_details import (
    ObjectDetailSources,
    load_hero_catalog,
    load_object_catalog,
    render_object_record,
)


_TABLES = OBJECT_TABLES
_PREFIX = re.compile(r"^\s*([^:：]+)[:：](.*)$", re.DOTALL)


class SearchSources(ObjectDetailSources, Protocol):
    pass


def query_search(
    pack: Path, query: str, limit: int, sources: SearchSources
) -> list[str]:
    """Search every object and matching field; only an explicit limit reduces output."""
    expression = sources._clean(query).strip()
    category = ""
    match = _PREFIX.match(expression)
    if match and (matched_category := object_category(match.group(1))) in _TABLES:
        category = matched_category
        expression = match.group(2).strip()
    if not expression and not category:
        return [
            "未找到: 查询词为空",
            "可输入关键词、四码或分类表达式，例如 search 物品:火焰 && 攻击。",
        ]
    compiled = compile_query(expression)
    if expression and compiled.is_empty:
        return [
            "未找到: 查询表达式没有关键词",
            '可输入关键词；组合使用 &&、||、%、括号或 ="精准词"。',
        ]
    total = 0
    output: list[str] = []
    catalog = (
        load_hero_catalog(pack, sources)
        if category == "英雄"
        else load_object_catalog(pack, (category,) if category else _TABLES, sources)
    )
    partial = any(not index.complete for index in catalog.values())
    for table, index in catalog.items():
        total += len(index.records)
        hits = [
            record
            for record in index.records
            if compiled.score_fields(record.search_fields(sources)) is not None
        ]
        if not hits:
            continue
        label = (
            "英雄类单位（原始分类：单位）"
            if category == "英雄" and table == "单位"
            else table
        )
        output.append(f"== {label} ({len(hits)} 个)==")
        for record in hits[:limit] if limit else hits:
            rendered = render_object_record(
                record, index.view, sources, include_description=False
            )
            output.append("  " + rendered[0])
            if description := sources._clean(record.row[6]):
                output.append("    说明: " + description)
            output.extend("  " + line for line in rendered[1:])
        if limit and len(hits) > limit:
            output.append(
                f"  (已达 --limit {limit}, 其余 {len(hits) - limit} 条未显示——去掉 --limit 看全量)"
            )
    if not output:
        scope = category + "表" if category else "对象八表"
        output = [
            "未找到: " + query,
            f"  本次已{'搜索已确认的' if partial else '完整搜索'}{scope} {total} 项的名称、ID、基础ID、说明、完整对象字段及扩展文本。",
            "  可缩短关键词或改用 物品:火焰 && 攻击 等分类表达式；其他证据入口: recipe / where / cmd / quest / affixes / registered / price。",
        ]
    if partial:
        output.append(
            "  数据源有诊断，以上为已确认记录；记录数不代表完整地图总量，请核对来源诊断或用 text <词> 查原文。"
        )
    return output

"""Complete, scoped object-text search using the shared Boolean query language."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Protocol

from .search import compile_query
from .pack_query_objects import OBJECT_TABLES


_TABLES = OBJECT_TABLES
_ALIASES = {
    **{table: table for table in _TABLES},
    "item": "物品",
    "items": "物品",
    "unit": "单位",
    "units": "单位",
    "skills": "技能",
    "abilities": "技能",
    "heroes": "英雄",
    "buffs": "增益",
    "tech": "科技",
    "doodads": "装饰物",
    "destructables": "可破坏物",
}
_PREFIX = re.compile(r"^\s*([^:：]+)[:：](.*)$", re.DOTALL)


class SearchSources(Protocol):
    def _object_rows(self, pack: Path, table: str) -> tuple[tuple[str, ...], ...]: ...
    def _clean(self, text: str) -> str: ...


def query_search(
    pack: Path, query: str, limit: int, sources: SearchSources
) -> list[str]:
    """Search every object and matching field; only an explicit limit reduces output."""
    expression = sources._clean(query).strip()
    category = ""
    match = _PREFIX.match(expression)
    if match and (matched_category := _ALIASES.get(match.group(1).strip().casefold())):
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
    invalid_rows = 0
    output: list[str] = []
    for table in (category,) if category else _TABLES:
        rows = sources._object_rows(pack, table)
        if not rows:
            continue
        hits: list[tuple[str, str, tuple[tuple[str, str], ...]]] = []
        for row in rows[1:]:
            if not row:
                continue
            if (
                len(row) < 5
                or len(row[1]) != 4
                or any(ord(char) > 255 for char in row[1])
            ):
                invalid_rows += 1
                continue
            total += 1
            code, name = row[1], sources._clean(row[4])
            fields = [("数值", row[2]), ("基础ID", row[3])]
            fields.extend(
                (
                    rows[0][i]
                    if i < len(rows[0])
                    else "说明"
                    if i == 6
                    else f"扩展字段{i + 1}",
                    sources._clean(value),
                )
                for i, value in enumerate(row[6:], start=6)
                if value
            )
            if (
                compiled.score_fields(
                    (code, name, *(value for _label, value in fields))
                )
                is None
            ):
                continue
            details = tuple((label, value) for label, value in fields if value)
            hits.append((code, name, details))
        if not hits:
            continue
        output.append(f"== {table} ({len(hits)} 个)==")
        for code, name, details in hits[:limit] if limit else hits:
            output.append(f"  [{code}] {name}")
            output.extend(f"    {label}: {value}" for label, value in details)
        if limit and len(hits) > limit:
            output.append(
                f"  (已达 --limit {limit}, 其余 {len(hits) - limit} 条未显示——去掉 --limit 看全量)"
            )
    if not output:
        scope = category + "表" if category else "对象八表"
        output = [
            "未找到: " + query,
            f"  本次已完整搜索{scope} {total} 项的名称、ID、基础ID、说明及扩展文本。",
            "  可缩短关键词或改用 物品:火焰 && 攻击 等分类表达式；其他证据入口: recipe / where / cmd / quest / affixes / registered / price。",
        ]
    if invalid_rows:
        output.append(
            f"  ⚠ 对象表有 {invalid_rows} 行字段不完整或不是四字节对象码，请核对知识包或重新导出。"
        )
    return output

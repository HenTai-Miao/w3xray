"""Complete dedicated object queries over ID rows and known field evidence."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from .object_codes import decode_object_id_query
from .base_names import BASE_CATEGORIES
from .pack_query_field_evidence import ObjectFields, object_field_indexes
from .pack_query_objects import ObjectTable
from .pack_query_combat_evidence import render_combat_parameters
from .pack_query_unit_abilities import UnitAbilityEvidence, unit_ability_evidence
from .search import compile_query


class ObjectDetailSources(Protocol):
    def _named_table(
        self, pack: Path, relative: str, table: str = ""
    ) -> ObjectTable: ...
    def _clean(self, text: str) -> str: ...


@dataclass(frozen=True, slots=True)
class ObjectRecord:
    row: tuple[str, ...]
    evidence: ObjectFields
    from_fields: bool = False
    unit_abilities: UnitAbilityEvidence | None = None
    fields_complete: bool = True
    hero_basis: str = ""

    def search_fields(self, sources: ObjectDetailSources) -> Iterator[str]:
        yield self.row[1]
        if not self.from_fields:
            yield sources._clean(self.row[4])
        yield from self.evidence.names
        yield from (sources._clean(value) for value in (*self.row[2:4], *self.row[5:]))
        for field in self.evidence.fields:
            yield from field.search_fields(sources._clean)
        if self.unit_abilities is not None:
            yield from self.unit_abilities.search_fields()


@dataclass(frozen=True, slots=True)
class ObjectDetailIndex:
    view: ObjectTable
    field_view: ObjectTable
    records: tuple[ObjectRecord, ...]

    @property
    def complete(self) -> bool:
        return self.view.complete and self.field_view.complete


def load_object_catalog(
    pack: Path, tables: Iterable[str], sources: ObjectDetailSources
) -> dict[str, ObjectDetailIndex]:
    requested = tuple(dict.fromkeys(tables))
    field_view = sources._named_table(pack, "对象字段.tsv")
    field_categories = (
        (*requested, "技能")
        if any(table in {"单位", "英雄"} for table in requested)
        else requested
    )
    fields = object_field_indexes(field_view.rows, field_categories, sources._clean)
    ability_search: dict[str, tuple[str, ...]] = {}

    def make_record(
        row: tuple[str, ...], evidence: ObjectFields, from_fields: bool = False
    ) -> ObjectRecord:
        abilities = (
            unit_ability_evidence(
                evidence.fields,
                fields.get("技能", {}),
                sources._clean,
                fields_complete=field_view.complete,
                search_cache=ability_search,
            )
            if row[0] in {"单位", "英雄"}
            else None
        )
        return ObjectRecord(row, evidence, from_fields, abilities, field_view.complete)

    catalog: dict[str, ObjectDetailIndex] = {}
    for table in requested:
        view = sources._named_table(pack, f"对象ID/{table}.tsv", table)
        index = fields.get(table, {})
        records = [
            make_record(row, index.get(row[1]) or ObjectFields(row[1], (), ()))
            for row in view.rows[1:]
            if len(row) > 4
        ]
        known = {record.row[1] for record in records}
        records.extend(
            make_record(
                (table, code, "", "", " / ".join(evidence.names) or code, "", ""),
                evidence,
                True,
            )
            for code, evidence in index.items()
            if code not in known
        )
        catalog[table] = ObjectDetailIndex(view, field_view, tuple(records))
    return catalog


def load_object_records(
    pack: Path, table: str, sources: ObjectDetailSources
) -> ObjectDetailIndex:
    return load_object_catalog(pack, (table,), sources)[table]


def load_hero_catalog(
    pack: Path, sources: ObjectDetailSources
) -> dict[str, ObjectDetailIndex]:
    """Include unit records whose unique declared base is a catalog hero.

    W3U heroes retain their unit category. A missing or conflicting base never
    falls back to the object's spelling, name, attributes or another category.
    """
    catalog = load_object_catalog(pack, ("英雄", "单位"), sources)
    units = catalog["单位"]
    bases: dict[str, set[str]] = {}
    for record in units.records:
        if not record.from_fields:
            bases.setdefault(record.row[1], set()).add(record.row[3])
    selected: list[ObjectRecord] = []
    for record in units.records:
        declared = bases.get(record.row[1], set())
        base = record.row[3]
        if (
            record.from_fields
            or len(declared) != 1
            or BASE_CATEGORIES.get(base, ("", ""))[0] != "英雄"
        ):
            continue
        selected.append(replace(record, hero_basis=base))
    catalog["单位"] = replace(units, records=tuple(selected))
    return catalog


def render_object_record(
    record: ObjectRecord,
    view: ObjectTable,
    sources: ObjectDetailSources,
    *,
    include_description: bool = True,
) -> list[str]:
    out: list[str] = []
    row = record.row
    name = sources._clean(row[4]) or " / ".join(record.evidence.names) or row[1]
    custom, note = row[5].strip(), sources._clean(row[6])
    origin = (
        "自定义" if custom == "是" else "继承基础" if custom == "否" else "来源未记录"
    )
    out.append(
        f"[{row[1]}] {name} ({origin})"
        + (" — " + note if note and include_description else "")
    )
    if record.hero_basis:
        out.append(
            "  英雄分类依据: 对象ID/单位.tsv 明确声明基础 ID "
            + record.hero_basis
            + "，内置基础目录将其列为英雄；原始分类仍为单位。"
        )
        out.append("  该静态分类不证明当前可选、已生成或由玩家持有。")
    if record.from_fields:
        out.append(
            "  该对象由对象字段.tsv确认；ID 清单未收录，基础 ID 及自定义标记未记录。"
        )
    elif record.evidence.names and any(
        alias != name for alias in record.evidence.names
    ):
        out.append("  字段记录名称: " + " / ".join(record.evidence.names))
    details = [("数值", row[2]), ("基础ID", row[3]), ("自定义标记", row[5])]
    details.extend(
        (view.rows[0][index], value) for index, value in enumerate(row[7:], 7)
    )
    out.extend(
        f"  {label}: {sources._clean(value)}" for label, value in details if value
    )
    out.extend(
        render_combat_parameters(
            row[0], record.evidence.fields, complete=record.fields_complete
        )
    )
    if record.unit_abilities is not None:
        out.extend(record.unit_abilities.render_lines())
    if record.evidence.fields:
        out.append("  完整对象字段:")
        for field in record.evidence.fields:
            out.extend(field.render_lines())
    else:
        out.append(
            f"  对象字段未记录；可用 doc {row[1]} / text {row[1]} 查证或重新导出。"
        )
    return out


def query_object_details(
    pack: Path, query: str, table: str, limit: int, sources: ObjectDetailSources
) -> list[str]:
    selected_id = decode_object_id_query(query.strip())
    expression = "" if selected_id is not None else sources._clean(query).strip()
    compiled = compile_query(expression)
    if expression and compiled.is_empty:
        return [
            "未找到: 查询表达式没有关键词",
            '可输入名称、四码、字段词；组合使用 &&、||、%、括号或 ="精准词"。',
        ]
    catalog = (
        load_hero_catalog(pack, sources)
        if table == "英雄"
        else {table: load_object_records(pack, table, sources)}
    )
    records = [
        (record, index.view) for index in catalog.values() for record in index.records
    ]
    matches = [
        (record, view)
        for record, view in records
        if (
            record.row[1] == selected_id
            if selected_id is not None
            else not expression
            or compiled.score_fields(record.search_fields(sources)) is not None
        )
    ]
    partial = any(not index.complete for index in catalog.values())
    if not matches:
        return [
            "未找到: " + (query or table + "对象记录") + " (名称/ID/说明/完整字段过滤)",
            f"  本次可确认{table}对象记录共 {len(records)} 项；可换名称、四码或字段关键词，用 search <词> 跨八表查。",
            f"  数据来源: 对象ID/{table}.tsv{'、对象ID/单位.tsv 的明确英雄基础 ID' if table == '英雄' else ''} 与 对象字段.tsv；缺失时请重新导出，可用 text <词> 查其他文本。",
            "  若有坐标，可用 near <x> <y> 反查附近对象。",
            *(
                [
                    "  单位记录缺少或冲突的基础 ID 不用于推断英雄身份；可用 units <名称或四码> / search <词> 继续查原始证据。"
                ]
                if table == "英雄"
                else []
            ),
            *(
                ["  数据源有诊断，当前已确认记录数不代表完整地图总量。"]
                if partial
                else []
            ),
        ]
    out: list[str] = []
    for record, view in matches[:limit] if limit else matches:
        out.extend(render_object_record(record, view, sources))
    if limit and len(matches) > limit:
        out.append(
            f"  (已达 --limit {limit}, 其余 {len(matches) - limit} 条未显示——去掉 --limit 看全量)"
        )
    if partial:
        out.append("  数据源有诊断，以上为已确认对象记录；完整性边界见来源诊断。")
    return out

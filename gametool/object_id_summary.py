"""Per-object-ID source counts for static investigation exports."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .api import GameObject, MapData
from .base_catalog import english_name_for, fine_category_for
from .base_names import BASE_NAMES
from .knowledge_io import tsv
from .object_id_usage import ObjectIdUsageReport, build_object_id_usage, code_decimal
from .save_analysis import SaveReport, SaveClue, build_save_report


@dataclass(frozen=True, slots=True)
class PreplacedCodeUse:
    code: str
    detail: str


def format_object_id_usage_summary(md: MapData) -> str:
    """Return per-ID usage counts across script, save, fields and preplaced data."""
    usage = build_object_id_usage(md)
    save_report = build_save_report(md)
    field_counts = {code: len(rows) for code, rows in md.referenced_by.items()}
    preplaced = tuple(preplaced_code_uses(md))
    object_lookup = _object_lookup(md)
    codes = _summary_codes(object_lookup, usage, save_report, field_counts, preplaced)
    # 每个 ID 的计数/详情原本要全量扫脚本条目、存档行、预放置各 2-3 遍，
    # 千级 ID 时是千万次比较；先按码分组一次，行序保持原顺序。
    script_counts = Counter(entry.code for entry in usage.entries)
    save_rows_by_code: dict[str, list[SaveClue]] = defaultdict(list)
    for row in save_report.rows:
        for code in row.object_codes:
            save_rows_by_code[code].append(row)
    preplaced_by_code: dict[str, list[PreplacedCodeUse]] = defaultdict(list)
    for use in preplaced:
        preplaced_by_code[use.code].append(use)
    rows = [
        "ID\t10进制\t分类\t名称\t对象来源\t脚本引用\t存档/ID线索\t对象字段引用"
        "\t预放置引用\t状态\t详情\t英文名\t细类"
    ]
    for code in codes:
        objects = object_lookup.get(code, ())
        save_rows = save_rows_by_code.get(code, ())
        placed = preplaced_by_code.get(code, ())
        rows.append(
            "\t".join(
                (
                    tsv(code),
                    str(code_decimal(code)),
                    tsv(_category(objects)),
                    tsv(_name(objects, code)),
                    tsv(_source(objects)),
                    str(script_counts.get(code, 0)),
                    str(len(save_rows)),
                    str(field_counts.get(code, 0)),
                    str(len(placed)),
                    tsv(
                        _status(
                            objects,
                            script_counts.get(code, 0),
                            len(save_rows),
                            field_counts.get(code, 0),
                            len(placed),
                        )
                    ),
                    tsv(_detail(md, usage, save_rows, placed, code)),
                    tsv(_english_name(objects, code)),
                    tsv(_fine_category(objects, code)),
                )
            )
        )
    return "\n".join(rows) + "\n"


def preplaced_code_counts(md: MapData) -> Counter[str]:
    """Return counts of object IDs found in preplaced units, items, abilities and drops."""
    return Counter(use.code for use in preplaced_code_uses(md))


def preplaced_code_uses(md: MapData) -> Iterable[PreplacedCodeUse]:
    """Yield object IDs referenced by parsed preplaced units and doodads."""
    for unit in md.units:
        yield PreplacedCodeUse(unit.type_id, "单位类型")
        for item_id, _chance in unit.drops:
            yield PreplacedCodeUse(item_id, "单位掉落")
        for slot, item_id in unit.items:
            yield PreplacedCodeUse(item_id, f"单位物品栏:{slot}")
        for ability_id, _active, _level in unit.abilities:
            yield PreplacedCodeUse(ability_id, "单位技能")
    for doodad in md.doodads:
        yield PreplacedCodeUse(doodad.type_id, "装饰物类型")
        for item_id, _chance in doodad.drops:
            yield PreplacedCodeUse(item_id, "装饰物掉落")


def _summary_codes(
    object_lookup: dict[str, tuple[GameObject, ...]],
    usage: ObjectIdUsageReport,
    save_report: SaveReport,
    field_counts: dict[str, int],
    preplaced: tuple[PreplacedCodeUse, ...],
) -> tuple[str, ...]:
    codes = set(object_lookup)
    codes.update(usage.codes)
    codes.update(save_report.object_codes)
    codes.update(field_counts)
    codes.update(use.code for use in preplaced)
    return tuple(sorted(codes))


def _object_lookup(md: MapData) -> dict[str, tuple[GameObject, ...]]:
    grouped: dict[str, dict[tuple[str, str, str, str], GameObject]] = {}
    for obj in (
        *(obj for objects in md.objects.values() for obj in objects),
        *md.obj_index.values(),
    ):
        identity = (obj.category, obj.base_id, obj.ext, obj.name)
        grouped.setdefault(obj.obj_id, {}).setdefault(identity, obj)
    return {
        code: tuple(rows[key] for key in sorted(rows)) for code, rows in grouped.items()
    }


def _category(objects: tuple[GameObject, ...]) -> str:
    return "/".join(dict.fromkeys(obj.category for obj in objects)) or "未知"


def _name(objects: tuple[GameObject, ...], code: str) -> str:
    if objects:
        return _joined_objects(objects, lambda obj: obj.name)
    return BASE_NAMES.get(code) or english_name_for(code) or ""


def _english_name(objects: tuple[GameObject, ...], code: str) -> str:
    """英文名按基础码优先（自定义对象显示其基底英文名）。"""
    if not objects:
        return english_name_for(code)
    return _joined_objects(
        objects, lambda obj: english_name_for(obj.base_id, code, category=obj.category)
    )


def _fine_category(objects: tuple[GameObject, ...], code: str) -> str:
    if not objects:
        return fine_category_for(code)
    return _joined_objects(
        objects, lambda obj: fine_category_for(obj.base_id, code, category=obj.category)
    )


def _source(objects: tuple[GameObject, ...]) -> str:
    return _joined_objects(objects, lambda obj: obj.ext) if objects else "未解析"


def _joined_objects(
    objects: tuple[GameObject, ...], render: Callable[[GameObject], str]
) -> str:
    if len(objects) == 1:
        return render(objects[0])
    return " / ".join(f"{obj.category}:{render(obj)}" for obj in objects)


def _status(
    objects: tuple[GameObject, ...],
    script_count: int,
    save_count: int,
    field_count: int,
    preplaced_count: int,
) -> str:
    used = script_count > 0 or save_count > 0 or field_count > 0 or preplaced_count > 0
    if not objects:
        return "未在对象表中解析"
    state = "已解析" if used else "仅对象表"
    if len(objects) > 1:
        state += "；同码对象来源计数按ID汇总，未归属到单一类别"
    return state


def _detail(
    md: MapData,
    usage: ObjectIdUsageReport,
    save_rows: tuple[SaveClue, ...] | list[SaveClue],
    placed: tuple[PreplacedCodeUse, ...] | list[PreplacedCodeUse],
    code: str,
) -> str:
    parts: list[str] = []
    script = usage.details_for(code)
    if script:
        parts.append(f"脚本={';'.join(script)}")
    save = tuple(f"{row.source}:{row.line}:{row.operation}" for row in save_rows)
    if save:
        parts.append(f"存档/ID={';'.join(sorted(set(save)))}")
    fields = tuple(
        f"{owner}:{field}" for owner, _name, field in md.referenced_by.get(code, ())
    )
    if fields:
        parts.append(f"对象字段={';'.join(sorted(set(fields)))}")
    if placed:
        parts.append(f"预放置={';'.join(sorted({use.detail for use in placed}))}")
    return "；".join(parts)

"""Per-object-ID source counts for static investigation exports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from .api import GameObject, MapData
from .base_names import BASE_NAMES
from .knowledge_io import tsv
from .object_id_usage import ObjectIdUsageReport, build_object_id_usage, code_decimal
from .save_analysis import SaveReport, build_save_report


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
    rows = ["ID\t10进制\t分类\t名称\t对象来源\t脚本引用\t存档/ID线索\t对象字段引用\t预放置引用\t状态\t详情"]
    for code in codes:
        obj = object_lookup.get(code)
        rows.append("\t".join((
            tsv(code),
            str(code_decimal(code)),
            tsv(_category(obj)),
            tsv(_name(obj, code)),
            tsv(_source(obj)),
            str(_script_count(usage, code)),
            str(_save_count(save_report, code)),
            str(field_counts.get(code, 0)),
            str(_preplaced_count(preplaced, code)),
            tsv(_status(obj, code, usage, save_report, field_counts, preplaced)),
            tsv(_detail(md, usage, save_report, preplaced, code)),
        )))
    return "\n".join(rows) + "\n"


def preplaced_code_counts(md: MapData) -> Counter[str]:
    """Return counts of object IDs found in preplaced units, items, abilities and drops."""
    return Counter(use.code for use in preplaced_code_uses(md))


def preplaced_code_uses(md: MapData) -> Iterable[PreplacedCodeUse]:
    """Yield object IDs referenced by parsed preplaced units and doodads."""
    for unit in md.units:
        yield PreplacedCodeUse(unit.type_id, "单位类型")
        for slot, item_id in unit.items:
            yield PreplacedCodeUse(item_id, f"单位物品栏:{slot}")
        for ability_id, _active, _level in unit.abilities:
            yield PreplacedCodeUse(ability_id, "单位技能")
    for doodad in md.doodads:
        yield PreplacedCodeUse(doodad.type_id, "装饰物类型")
        for item_id, _chance in doodad.drops:
            yield PreplacedCodeUse(item_id, "装饰物掉落")


def _summary_codes(
    object_lookup: dict[str, GameObject],
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


def _object_lookup(md: MapData) -> dict[str, GameObject]:
    lookup = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
    for code, obj in md.obj_index.items():
        if isinstance(code, str) and isinstance(obj, GameObject):
            lookup.setdefault(code, obj)
    return lookup


def _category(obj: GameObject | None) -> str:
    if obj is None:
        return "未知"
    return obj.category


def _name(obj: GameObject | None, code: str) -> str:
    if obj is not None:
        return obj.name
    return BASE_NAMES.get(code) or ""


def _source(obj: GameObject | None) -> str:
    if obj is None:
        return "未解析"
    return obj.ext


def _script_count(usage: ObjectIdUsageReport, code: str) -> int:
    return sum(1 for entry in usage.entries if entry.code == code)


def _save_count(save_report: SaveReport, code: str) -> int:
    return sum(1 for row in save_report.rows if code in row.object_codes)


def _preplaced_count(preplaced: tuple[PreplacedCodeUse, ...], code: str) -> int:
    return sum(1 for use in preplaced if use.code == code)


def _status(
    obj: GameObject | None,
    code: str,
    usage: ObjectIdUsageReport,
    save_report: SaveReport,
    field_counts: dict[str, int],
    preplaced: tuple[PreplacedCodeUse, ...],
) -> str:
    used = (
        _script_count(usage, code) > 0
        or _save_count(save_report, code) > 0
        or field_counts.get(code, 0) > 0
        or _preplaced_count(preplaced, code) > 0
    )
    if obj is None:
        return "未在对象表中解析"
    return "已解析" if used else "仅对象表"


def _detail(
    md: MapData,
    usage: ObjectIdUsageReport,
    save_report: SaveReport,
    preplaced: tuple[PreplacedCodeUse, ...],
    code: str,
) -> str:
    parts: list[str] = []
    script = usage.details_for(code)
    if script:
        parts.append(f"脚本={';'.join(script)}")
    save = tuple(f"{row.source}:{row.line}:{row.operation}" for row in save_report.rows if code in row.object_codes)
    if save:
        parts.append(f"存档/ID={';'.join(sorted(set(save)))}")
    fields = tuple(f"{owner}:{field}" for owner, _name, field in md.referenced_by.get(code, ()))
    if fields:
        parts.append(f"对象字段={';'.join(sorted(set(fields)))}")
    placed = tuple(use.detail for use in preplaced if use.code == code)
    if placed:
        parts.append(f"预放置={';'.join(sorted(set(placed)))}")
    return "；".join(parts)

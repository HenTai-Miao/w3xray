"""Preplaced unit and doodad TSV exports for knowledge packs."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import chain

from .api import GameObject, MapData
from .base_catalog import english_name_for, fine_category_for
from .base_names import BASE_NAMES
from .base_objects import BASE_OBJECTS
from .doo import Doodad, Unit
from .doo_drops import DropSet
from .knowledge_io import tsv
from .static_numbers import format_number as _num


@dataclass(frozen=True, slots=True)
class _PlacementLabel:
    name: str
    category: str
    english: str = ""
    fine: str = ""
    diagnostic: str = ""


class _ObjectNames:
    """One read-only category index per export, including legacy builder inputs."""

    def __init__(self, md: MapData) -> None:
        self.objects: dict[tuple[str, str], GameObject] = {}
        self.categories: dict[str, set[str]] = {}
        for obj in chain(
            chain.from_iterable(md.objects.values()),
            md.obj_identity_index.values(),
            md.obj_index.values(),
        ):
            category = "单位" if obj.category == "英雄" else obj.category
            identity = (category, obj.obj_id)
            previous = self.objects.get(identity)
            if previous is None or previous.ext == "script" and obj.ext != "script":
                self.objects[identity] = obj
            if obj.ext != "script":
                self.categories.setdefault(obj.obj_id, set()).add(category)
        self.names: dict[tuple[str, str], str] = {}
        self.placements: dict[tuple[str, tuple[str, ...]], _PlacementLabel] = {}

    def name(self, category: str, code: str) -> str:
        identity = (category, code)
        if identity not in self.names:
            obj = self.objects.get(identity)
            base = BASE_OBJECTS.get(code)
            if obj is not None and obj.ext != "script":
                self.names[identity] = obj.name or code
            elif base is not None and base[0] == category:
                self.names[identity] = (
                    BASE_NAMES.get(code) or english_name_for(code) or code
                )
            else:
                self.names[identity] = code
        return self.names[identity]

    def placement(self, code: str, allowed: tuple[str, ...]) -> _PlacementLabel:
        key = (code, allowed)
        if key in self.placements:
            return self.placements[key]
        known = set(self.categories.get(code, ()))
        base = BASE_OBJECTS.get(code)
        if base is not None:
            known.add(base[0])
        candidates = [category for category in allowed if category in known]
        if len(candidates) == 1:
            category = candidates[0]
            obj = self.objects.get((category, code))
            bases = (
                (obj.base_id, code)
                if obj is not None and obj.ext != "script"
                else (code,)
            )
            metadata_base = next(
                (
                    base_id
                    for base_id in bases
                    if (record := BASE_OBJECTS.get(base_id)) is not None
                    and record[0] == category
                ),
                "",
            )
            label = _PlacementLabel(
                self.name(category, code),
                category,
                english_name_for(metadata_base),
                fine_category_for(metadata_base),
            )
        elif candidates:
            label = _PlacementLabel(
                code,
                "",
                diagnostic="同码放置分类存在歧义，未猜测；候选: "
                + "；".join(
                    f"{category}: {self.name(category, code)}"
                    for category in candidates
                ),
            )
        else:
            label = _PlacementLabel(
                code,
                "",
                diagnostic="未找到已确认的"
                + "/".join(allowed)
                + "对象定义；已知分类: "
                + ("、".join(sorted(known)) or "无"),
            )
        self.placements[key] = label
        return label


def format_preplaced_units_tsv(md: MapData) -> str:
    """Return parsed war3mapUnits.doo placements as TSV."""
    rows = [
        "序号\t类型ID\t名称\t玩家\tX\tY\tZ\t角度\t生命\t魔法\t金矿\t英雄等级\t物品栏\t技能\t掉落\t英文名\t细类\t分类\t分类诊断"
    ]
    names = _ObjectNames(md)
    for unit in md.units:
        label = names.placement(unit.type_id, ("单位", "物品"))
        rows.append(
            "\t".join(
                (
                    str(unit.serial),
                    tsv(unit.type_id),
                    tsv(label.name),
                    str(unit.player),
                    _num(unit.x),
                    _num(unit.y),
                    _num(unit.z),
                    _num(unit.angle),
                    str(unit.hp),
                    str(unit.mana),
                    str(unit.gold),
                    str(unit.hero_level),
                    tsv(_format_unit_items(names, unit)),
                    tsv(_format_unit_abilities(names, unit)),
                    tsv(_format_drop_sets(names, unit.drop_sets)),
                    tsv(label.english),
                    tsv(label.fine),
                    tsv(label.category),
                    tsv(label.diagnostic),
                )
            )
        )
    return "\n".join(rows) + "\n"


def format_preplaced_doodads_tsv(md: MapData) -> str:
    """Return parsed war3map.doo doodad/destructable placements as TSV."""
    rows = [
        "序号\t类型ID\t名称\tX\tY\tZ\t角度\t缩放\t状态\t生命\t掉落\t英文名\t细类\t分类\t分类诊断"
    ]
    names = _ObjectNames(md)
    for doodad in md.doodads:
        label = names.placement(doodad.type_id, ("装饰物", "可破坏物"))
        rows.append(
            "\t".join(
                (
                    str(doodad.serial),
                    tsv(doodad.type_id),
                    tsv(label.name),
                    _num(doodad.x),
                    _num(doodad.y),
                    _num(doodad.z),
                    _num(doodad.angle),
                    tsv(_format_scale(doodad)),
                    str(doodad.flags),
                    str(doodad.life),
                    tsv(_format_drops(names, doodad)),
                    tsv(label.english),
                    tsv(label.fine),
                    tsv(label.category),
                    tsv(label.diagnostic),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _format_unit_items(names: _ObjectNames, unit: Unit) -> str:
    return "; ".join(
        f"{slot}:{_code_label(names, item_id, '物品')}" for slot, item_id in unit.items
    )


def _format_unit_abilities(names: _ObjectNames, unit: Unit) -> str:
    return "; ".join(
        f"{_code_label(names, ability_id, '技能')}:{_active_label(active)}:{level}"
        for ability_id, active, level in unit.abilities
    )


def _format_drops(names: _ObjectNames, doodad: Doodad) -> str:
    if doodad.drop_sets:
        return _format_drop_sets(names, doodad.drop_sets)
    return "; ".join(
        f"{_code_label(names, item_id, '物品')}:{chance}%"
        for item_id, chance in doodad.drops
    )


def _format_drop_sets(names: _ObjectNames, drop_sets: tuple[DropSet, ...]) -> str:
    return "；".join(
        f"组{group.group_index + 1}["
        + "; ".join(
            f"{_code_label(names, entry.item_id, '物品')}:{entry.chance}%"
            for entry in group.entries
        )
        + "]"
        for group in drop_sets
    )


def _format_scale(doodad: Doodad) -> str:
    return ",".join(_num(value) for value in doodad.scale)


def _code_label(names: _ObjectNames, code: str, category: str) -> str:
    return f"{code}({names.name(category, code)})"


def _active_label(active: int) -> str:
    return "启用" if active else "禁用"
